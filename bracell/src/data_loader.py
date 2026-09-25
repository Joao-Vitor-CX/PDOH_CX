# src/data_loader.py

import pandas as pd
from sqlalchemy import text

from .database import criar_engine, criar_engine_origem
from .data_quality import observar_qualidade
from .identity import observar_identidades, observar_identidades_entidades
from .de_para import observar_padronizacao
from .legacy_fallbacks import observar_fallback_jornada, observar_fallbacks_entrada
from .observability import (
    atualizar_periodo,
    iniciar_execucao,
    registrar_erro_tecnico,
    registrar_etapa,
    registrar_fonte,
)

# Quem tinha vinculo ativo em cada dia do periodo carregado ({'AAAA-MM-DD': {nomes}}).
# Preenchido por carregar_dados_involves; lido na persistencia da Platina (mesmo processo).
VIGENCIA_DO_PERIODO = {}


def nome_normalizado(valor):
    return ' '.join(str(valor or '').upper().split())


def deduplicar_pesquisas(df):
    """Uma pesquisa conta uma vez: versoes da mesma pesquisa (status mudou entre extracoes)
    ficam so' na mais recente (`data_evolucao`). Sem coluna `id`, nada muda."""
    if 'id' not in df.columns:
        return df
    if 'data_evolucao' in df.columns:
        ordem = pd.to_datetime(df['data_evolucao'], errors='coerce')
        df = df.assign(_ordem=ordem).sort_values('_ordem', ascending=False, kind='stable').drop(columns=['_ordem'])
    return df.drop_duplicates(subset=['id'], keep='first')


def cadastro_do_periodo(df_colaboradores, data_inicio=None, data_fim=None):
    """Cadastro vigente no PERIODO processado (nao o cadastro do dia da execucao).

    Para cada dia do periodo usa a extracao vigente naquele dia (a mais recente entre os registros
    com data_dimensao ate o dia) e mantem quem estava ativo. Entra quem esteve ativo em algum dia do
    periodo; o registro usado (inclusive a jornada `nome_pai`) e' o do ultimo dia ativo no periodo.
    Sem periodo informado, mantem o comportamento anterior (extracao mais recente).
    Devolve (dataframe, resumo) no mesmo formato que o tratamento legado espera.
    """
    df = df_colaboradores.copy()
    df['data_evolucao'] = pd.to_datetime(df['data_evolucao'], errors='coerce')
    df['data_dimensao'] = pd.to_datetime(df['data_dimensao'], errors='coerce')
    ativo = df['usuario_ativo'].astype('string').str.strip().str.lower() == 'sim'
    if not (data_inicio and data_fim):
        foto = df[df['data_evolucao'] == df['data_evolucao'].max()]
        foto = foto[ativo.loc[foto.index]]
        foto = foto.sort_values(by='data_dimensao', ascending=False).drop_duplicates(subset=['nome_colaborador'], keep='first')
        return foto.reset_index(drop=True), dict(modo='EXTRACAO_MAIS_RECENTE', extracoes=[str(df['data_evolucao'].max())[:10]])
    fotos, extracoes = [], {}
    for dia in pd.date_range(pd.to_datetime(data_inicio), pd.to_datetime(data_fim), freq='D'):
        validos = df[df['data_dimensao'] <= dia]
        if validos.empty:
            continue
        extracao = validos['data_evolucao'].max()
        foto = validos[(validos['data_evolucao'] == extracao) & ativo.loc[validos.index]]
        extracoes[str(dia.date())] = str(extracao)[:10]
        fotos.append(foto.assign(_dia_vigencia=dia))
    ativos_por_dia = {str(f['_dia_vigencia'].iloc[0].date()): {nome_normalizado(n) for n in f['nome_colaborador']}
                      for f in fotos if not f.empty}
    if not fotos:
        return df.iloc[0:0].reset_index(drop=True), dict(modo='PERIODO', extracoes=extracoes, ativos_por_dia={})
    unido = pd.concat(fotos)
    unido = unido.sort_values(by=['_dia_vigencia', 'data_dimensao'], ascending=False)
    unido = unido.drop_duplicates(subset=['nome_colaborador'], keep='first').drop(columns=['_dia_vigencia'])
    return unido.reset_index(drop=True), dict(modo='PERIODO', extracoes=extracoes, ativos_por_dia=ativos_por_dia)


def carregar_dados_involves(data_inicio: str = None, data_fim: str = None):
    # Observabilidade e persistencia permanecem sempre no ambiente local.
    db_config_local = {"database": "involves_bracell"}
    try:
        engine_local = criar_engine(db_config_local["database"])
        engine_origem = criar_engine_origem()
        # create_engine e lazy: estas consultas confirmam as duas comunicacoes.
        with engine_local.connect() as conexao:
            conexao.execute(text("SELECT 1"))
        with engine_origem.connect() as conexao:
            conexao.execute(text("SELECT 1"))
        print("Conexão com o banco de dados estabelecida com sucesso!")
        iniciar_execucao(
            engine_local,
            periodo_inicio=data_inicio,
            periodo_fim=data_fim,
        )
        atualizar_periodo(engine_local, data_inicio, data_fim)
        registrar_etapa(
            engine_local,
            etapa="ETL_CONSUMO",
            status="INICIADA",
            origem="INVOLVES_BRACELL",
            mensagem="Consumo das cinco fontes BRACELL iniciado.",
        )

    except Exception as e:
        print(f"ERRO CRÍTICO: Não foi possível conectar ao banco de dados: {e}")
        return None

    tabelas_a_carregar = {
        'relatorio_de_operacao': 'status_day_operacao_bracell',
        'colaboradores': 'colaboradores_ativos_bracell',
        'checkin': 'relatorio_checkin_bracell',
        'gerencial_de_visitas': 'gerencial_visitas_bracell',
        'pesquisas': 'painel_pesquisas_bracell'
    }

    colunas_de_data_para_filtrar = {
        'relatorio_de_operacao': 'dia_referencia',
        'checkin': 'data_roteiro',
        'gerencial_de_visitas': 'data_visita',
        'pesquisas': ['data_solicitacao', 'data_expiracao'],
        'colaboradores': 'data_dimensao'
    }

    dataframes = {}

    print("-" * 30)
    for nome_df, nome_tabela in tabelas_a_carregar.items():
        try:
            query = f"SELECT * FROM {nome_tabela}"

            if data_inicio and data_fim and nome_df in colunas_de_data_para_filtrar and nome_df != 'colaboradores':
                coluna_info = colunas_de_data_para_filtrar[nome_df]

                if isinstance(coluna_info, str):
                    where_clause = f" WHERE DATE({coluna_info}) BETWEEN '{data_inicio}' AND '{data_fim}'"
                elif isinstance(coluna_info, list):
                    condicoes_and = [f"DATE({col}) BETWEEN '{data_inicio}' AND '{data_fim}'" for col in coluna_info]
                    where_clause = " WHERE (" + " AND ".join(condicoes_and) + ")"

                query += where_clause
                print(f"Buscando dados da tabela: {nome_tabela} com filtro de data...")
            else:
                print(f"Buscando dados da tabela: {nome_tabela} (sem filtro de data)...")

            df_temp = pd.read_sql(query, engine_origem)

            linhas_antes = len(df_temp)
            # A verificacao e somente leitura e ocorre antes do tratamento atual.
            observar_qualidade(
                engine_local,
                df_temp,
                nome_df,
                nome_tabela,
                periodo_inicio=data_inicio,
                periodo_fim=data_fim,
            )
            observar_fallbacks_entrada(engine_local, df_temp, nome_df,
                                       source_engine=engine_origem,
                                       periodo_inicio=data_inicio, periodo_fim=data_fim)
            if nome_df != 'colaboradores':
                colunas_para_ignorar = ['data_dimensao', 'data_evolucao']
                colunas_para_verificar = [col for col in df_temp.columns if col not in colunas_para_ignorar]
                df_temp = df_temp.drop_duplicates(subset=colunas_para_verificar)
                if nome_df == 'pesquisas':
                    df_temp = deduplicar_pesquisas(df_temp)
                linhas_depois = len(df_temp)
                print(f" -> Tabela '{nome_df}' carregada com {linhas_depois} linhas ({linhas_antes - linhas_depois} duplicatas removidas).")
            else:
                print(f" -> Tabela '{nome_df}' carregada com {linhas_antes} linhas (tratamento de duplicatas específico será aplicado).")
            dataframes[nome_df] = df_temp
            registrar_fonte(
                engine_local,
                tabela_origem=nome_tabela,
                periodo_inicio=data_inicio,
                periodo_fim=data_fim,
                linhas_recebidas=linhas_antes,
                linhas_tratadas=len(df_temp),
                duplicatas=linhas_antes - len(df_temp),
                consulta=query,
            )
            registrar_etapa(
                engine_local,
                etapa="ETL_CONSUMO",
                status="FONTE_CONCLUIDA",
                origem="INVOLVES_BRACELL",
                tabela_origem=nome_tabela,
                linhas_recebidas=linhas_antes,
                linhas_tratadas=len(df_temp),
                mensagem=f"Fonte {nome_tabela} consumida.",
            )

        except Exception as e:
            print(f"ERRO: Falha ao carregar a tabela {nome_tabela}: {e}")
            registrar_erro_tecnico(
                engine_local,
                etapa="ETL_CONSUMO",
                mensagem=f"Falha ao carregar a tabela {nome_tabela}: {e}",
                excecao=e,
            )
            return None

    # A camada de identidade observa o conjunto bruto e nunca devolve dados ao calculo.
    observar_identidades(engine_local, dataframes)
    observar_identidades_entidades(engine_local, dataframes)
    observar_padronizacao(engine_local, dataframes)

    if 'colaboradores' in dataframes:
        print("\n-> Aplicando tratamento especial na tabela de colaboradores...")
        df_colaboradores = dataframes['colaboradores']

        linhas_antes_evolucao = len(df_colaboradores)
        df_colaboradores, vigencia = cadastro_do_periodo(df_colaboradores, data_inicio, data_fim)
        VIGENCIA_DO_PERIODO.clear()
        VIGENCIA_DO_PERIODO.update(vigencia.get('ativos_por_dia') or {})
        print(f"   - Cadastro vigente no periodo ({vigencia['modo']}): {len(df_colaboradores)} colaboradores ativos "
              f"de {linhas_antes_evolucao} registros; extracoes usadas por dia: {vigencia['extracoes']}")
        linhas_depois = len(df_colaboradores)

        dataframes['colaboradores'] = df_colaboradores
        observar_fallback_jornada(engine_local, df_colaboradores, source_engine=engine_origem)
        registrar_etapa(
            engine_local,
            etapa="TRATAMENTO_ENTRADA",
            status="CONCLUIDA",
            origem="INVOLVES_BRACELL",
            tabela_origem="colaboradores_ativos_bracell",
            linhas_recebidas=linhas_antes_evolucao,
            linhas_tratadas=len(df_colaboradores),
            mensagem=("Cadastro vigente no periodo aplicado (extracao de cada dia; ativos em algum dia; "
                      f"registro do ultimo dia ativo). Extracoes: {vigencia['extracoes']}"),
        )

    print("-" * 30)
    registrar_etapa(
        engine_local,
        etapa="ETL_CONSUMO",
        status="CONCLUIDA",
        origem="INVOLVES_BRACELL",
        linhas_recebidas=sum(len(df) for df in dataframes.values()),
        mensagem="Consumo e tratamento de entrada concluidos.",
    )
    return dataframes, engine_local
