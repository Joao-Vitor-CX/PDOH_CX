# src/alch.py

import pandas as pd
from sqlalchemy import text

from .observability import (
    iniciar_execucao,
    registrar_erro_tecnico,
    registrar_etapa,
    registrar_linhagem_saida,
    registrar_resultado_persistencia,
)

NOME_TABELA = "produtos_platina.exclusivo_bracell_platina_relatorio_pdoh"

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


def _valor_sql(valor):
    """Converte escalares pandas/numpy para tipos aceitos pelo driver MySQL."""

    if isinstance(valor, pd.Timestamp):
        return valor.to_pydatetime()
    if isinstance(valor, pd.Timedelta):
        return valor.to_pytimedelta()
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(valor, "item"):
        return valor.item()
    return valor


def filtrar_vinculo_do_dia(df, ativos_por_dia):
    """Mantem so' colaborador x dia com vinculo ativo no cadastro vigente naquele dia.

    O processador gera uma linha por dia para todo colaborador do cadastro do periodo; quem
    saiu no meio da semana (ou ainda nao tinha entrado) nao pode ganhar horas programadas nos
    dias sem vinculo. Dias sem cadastro conhecido nao sao filtrados. Devolve (df, removidas).
    """
    if not ativos_por_dia or df.empty or not {'colaborador', 'data'} <= set(df.columns):
        return df, []
    dias = pd.to_datetime(df['data'], errors='coerce').dt.strftime('%Y-%m-%d')
    nomes = df['colaborador'].map(lambda v: ' '.join(str(v or '').upper().split()))
    manter = [dia not in ativos_por_dia or nome in ativos_por_dia[dia] for dia, nome in zip(dias, nomes)]
    mascara = pd.Series(manter, index=df.index)
    removidas = sorted({(n, d) for n, d, m in zip(nomes, dias, manter) if not m})
    return df[mascara].copy(), removidas


def _identificador(nome):
    return f"`{str(nome).replace('`', '``')}`"


def inserir_produto(df, engine, *, connection=None):
    """
    Realiza um "UPSERT" (INSERT ou UPDATE) de um DataFrame na tabela Platina.

    Executa o mesmo INSERT ... ON DUPLICATE KEY UPDATE diretamente, sem exigir
    privilegios DDL da conta da aplicacao. Se um registro com a mesma chave
    unica (colaborador, data) ja existe, ele e atualizado; caso contrario, e
    inserido.

    Substitui a antiga estrategia de DELETE da janela [min(data), max(data)]
    seguida de carga tabular em modo append. O UPSERT e' idempotente sem
    precisar apagar nada, entao um run que falhe no meio nao deixa mais a
    janela vazia na tabela Platina.

    Diferenca de comportamento em relacao ao DELETE+append: linhas de
    colaboradores que sairam da operacao permanecem na Platina em vez de serem
    removidas (o snapshot de colaboradores usado no calculo e' sempre o atual).

    Args:
        df: O DataFrame a ser inserido/atualizado.
        engine: O objeto de conexão SQLAlchemy.
        connection: Conexao transacional opcional, usada somente pelos testes
            tecnicos que precisam validar e reverter a linha sintetica.
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

    from .data_loader import VIGENCIA_DO_PERIODO
    df, removidas = filtrar_vinculo_do_dia(df, VIGENCIA_DO_PERIODO)
    if removidas:
        registrar_etapa(
            engine,
            etapa="VINCULO_DO_DIA",
            status="CONCLUIDA",
            linhas_geradas=len(removidas),
            mensagem=(f"{len(removidas)} linha(s) sem vinculo no cadastro do dia nao foram gravadas: "
                      + ", ".join(f"{n} {d}" for n, d in removidas[:30])),
        )
        print(f" -> {len(removidas)} linha(s) colaborador x dia sem vinculo no cadastro do dia descartadas.")
    if df.empty:
        return

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
    parametros = [f"valor_{indice}" for indice in range(len(cols))]
    registros = [
        {
            parametro: _valor_sql(valor)
            for parametro, valor in zip(parametros, linha)
        }
        for linha in df.itertuples(index=False, name=None)
    ]

    # Monta a parte UPDATE — colunas que NÃO são chave primária
    update_cols = [
        f"{_identificador(col)} = VALUES({_identificador(col)})"
        for col in cols
        if col.lower() not in COLUNAS_CHAVE
    ]
    update_clause = ", ".join(update_cols)
    colunas_sql = ", ".join(_identificador(col) for col in cols)
    valores_sql = ", ".join(f":{parametro}" for parametro in parametros)

    upsert_query = text(f"""
        INSERT INTO {NOME_TABELA} ({colunas_sql})
        VALUES ({valores_sql})
        ON DUPLICATE KEY UPDATE {update_clause};
    """)

    conexao_propria = connection is None
    conexao = connection or engine.connect()
    transaction = conexao.begin() if conexao_propria else None
    try:
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

        print(" -> Executando INSERT ... ON DUPLICATE KEY UPDATE direto...")
        result = conexao.execute(upsert_query, registros)

        if transaction is not None:
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
        if transaction is not None and transaction.is_active:
            transaction.rollback()
        registrar_erro_tecnico(
            engine,
            etapa="PERSISTENCIA_PLATINA",
            mensagem=f"Falha durante o UPSERT Platina: {e}",
            excecao=e,
        )
    finally:
        if conexao_propria:
            try:
                if transaction is not None and transaction.is_active:
                    transaction.rollback()
            finally:
                conexao.close()
