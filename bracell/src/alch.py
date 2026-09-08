# src/alch.py

import pandas as pd
from sqlalchemy import text

from .observability import (
    iniciar_execucao,
    obter_execution_id,
    registrar_erro_tecnico,
    registrar_etapa,
    registrar_linhagem_saida,
    registrar_resultado_persistencia,
)

NOME_TABELA = "produtos_platina.exclusivo_bracell_platina_relatorio_pdoh"
SCHEMA_TEMPORARIO = "produtos_platina"

# Colunas da chave unica `uk_pdoh_colab_data` da Platina — nao entram no UPDATE.
COLUNAS_CHAVE = ("colaborador", "data")


def _normalizar_vazios(df, engine):
    """
    Converte string vazia ('') em None nas colunas cujo tipo no destino nao e' textual.

    O pipeline usa '' para "nao se aplica" (ex.: colaborador sem jornada no dia),
    mas o MySQL roda em STRICT_TRANS_TABLES: '' em coluna DECIMAL/TIME/DATE e'
    rejeitado com o erro 1366 ("Incorrect decimal value"). Como essas colunas sao
    nullable, NULL preserva a semantica de "sem valor" sem inventar zero.

    Isso ja quebrava no antigo to_sql(append) — a excecao so era engolida pelo
    try/except do chamador, e as linhas sumiam em silencio.
    """
    schema, _, tabela = NOME_TABELA.partition(".")
    consulta = text(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = :s AND table_name = :t"
    )
    with engine.connect() as conexao:
        tipos = {n: t for n, t in conexao.execute(consulta, {"s": schema, "t": tabela})}

    textuais = {"char", "varchar", "text", "tinytext", "mediumtext", "longtext", "enum", "set", "json"}
    alvo = [c for c in df.columns if tipos.get(c) and tipos[c] not in textuais]
    if not alvo:
        return df

    df = df.copy()
    for coluna in alvo:
        if df[coluna].dtype == object:
            df[coluna] = df[coluna].replace("", None)
    return df


def inserir_produto(df, engine):
    """
    Realiza um "UPSERT" (INSERT ou UPDATE) de um DataFrame na tabela Platina.

    Utiliza uma tabela temporária para garantir performance e segurança.
    Se um registro com a mesma chave única (colaborador, data) já existe,
    ele será atualizado; caso contrário, será inserido.

    Substitui a antiga estrategia de DELETE da janela [min(data), max(data)]
    seguida de df.to_sql(if_exists='append'). O UPSERT e' idempotente sem
    precisar apagar nada, entao um run que falhe no meio nao deixa mais a
    janela vazia na tabela Platina.

    Diferenca de comportamento em relacao ao DELETE+append: linhas de
    colaboradores que sairam da operacao permanecem na Platina em vez de serem
    removidas (o snapshot de colaboradores usado no calculo e' sempre o atual).

    Args:
        df: O DataFrame a ser inserido/atualizado.
        engine: O objeto de conexão SQLAlchemy.
    """
    iniciar_execucao(engine)
    if df.empty:
        print("\nDataFrame está vazio. Nenhuma operação de inserção no banco de dados será realizada.")
        registrar_etapa(
            engine,
            etapa="PERSISTENCIA_PLATINA",
            status="SEM_RESULTADO",
            linhas_geradas=0,
            linhas_persistidas=0,
            mensagem="DataFrame final vazio; comportamento atual preservado.",
        )
        return

    # Sufixo tecnico: evita colisao entre execucoes, sem alterar dados de negocio.
    sufixo_execucao = "".join(
        caractere.lower() for caractere in (obter_execution_id() or "sem_id") if caractere.isalnum()
    )[-16:]
    nome_tabela_temporaria = f"tmp_pdoh_platina_{sufixo_execucao}"

    try:
        df = _normalizar_vazios(df, engine)
    except Exception as exc:
        registrar_erro_tecnico(
            engine,
            etapa="PERSISTENCIA_PLATINA",
            mensagem=f"Falha ao preparar tipos para a persistencia Platina: {exc}",
            excecao=exc,
        )
        raise

    cols = df.columns.tolist()

    # Monta a parte UPDATE — colunas que NÃO são chave primária
    update_cols = [f"`{col}` = VALUES(`{col}`)" for col in cols if col.lower() not in COLUNAS_CHAVE]
    update_clause = ", ".join(update_cols)

    upsert_query = text(f"""
        INSERT INTO {NOME_TABELA} (`{'`, `'.join(cols)}`)
        SELECT `{'`, `'.join(cols)}`
        FROM `{SCHEMA_TEMPORARIO}`.`{nome_tabela_temporaria}`
        ON DUPLICATE KEY UPDATE {update_clause};
    """)

    with engine.connect() as connection:
        transaction = None
        try:
            transaction = connection.begin()
            print(f"\nIniciando processo de UPSERT para a tabela '{NOME_TABELA}'...")
            registrar_etapa(
                engine,
                etapa="PROCESSAMENTO_PDOH",
                status="CONCLUIDA",
                linhas_geradas=len(df),
                mensagem="Resultado PDOH entregue para persistencia sem alteracao de calculo.",
            )
            registrar_etapa(
                engine,
                etapa="PERSISTENCIA_PLATINA",
                status="INICIADA",
                linhas_geradas=len(df),
                mensagem="UPSERT Platina iniciado.",
            )

            # Passo 1: Envia dados para tabela temporária
            print(f" -> Criando tabela temporária '{nome_tabela_temporaria}' com {len(df)} registros...")
            df.to_sql(nome_tabela_temporaria,
                      con=connection,
                      schema=SCHEMA_TEMPORARIO,
                      if_exists='replace',
                      index=False)

            # Passo 2: Executa UPSERT
            print(f" -> Executando INSERT ... ON DUPLICATE KEY UPDATE...")
            result = connection.execute(upsert_query)

            # Passo 3: Commit
            transaction.commit()
            print(f" -> Processo concluído com sucesso. Linhas afetadas: {result.rowcount}.")
            registrar_resultado_persistencia(
                engine,
                linhas_geradas=len(df),
                linhas_persistidas=len(df),
                afetadas_banco=result.rowcount,
            )
            registrar_linhagem_saida(engine, df, NOME_TABELA)

        except Exception as e:
            print(f"ERRO durante o processo de UPSERT: {e}")
            if transaction:
                transaction.rollback()
            registrar_erro_tecnico(
                engine,
                etapa="PERSISTENCIA_PLATINA",
                mensagem=f"Falha durante o UPSERT Platina: {e}",
                excecao=e,
            )
        finally:
            # Passo 4: Remove tabela temporária
            print(f" -> Removendo tabela temporária...")
            try:
                connection.execute(text(
                    f"DROP TABLE IF EXISTS `{SCHEMA_TEMPORARIO}`.`{nome_tabela_temporaria}`"
                ))
                connection.commit()
            except Exception:
                pass
