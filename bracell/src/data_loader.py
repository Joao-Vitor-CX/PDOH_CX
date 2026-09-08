# src/data_loader.py

import pandas as pd
from sqlalchemy import text

from .database import criar_engine
from .data_quality import observar_qualidade
from .identity import observar_identidades
from .legacy_fallbacks import observar_fallback_jornada, observar_fallbacks_entrada
from .observability import (
    atualizar_periodo,
    iniciar_execucao,
    registrar_erro_tecnico,
    registrar_etapa,
    registrar_fonte,
)

def carregar_dados_involves(data_inicio: str = None, data_fim: str = None):
    # Mantem explicito o contrato da origem local desta replica.
    db_config = {"database": "involves_bracell"}
    try:
        engine = criar_engine(db_config["database"])
        # create_engine e lazy: esta consulta confirma a comunicacao de verdade.
        with engine.connect() as conexao:
            conexao.execute(text("SELECT 1"))
        print("Conexão com o banco de dados estabelecida com sucesso!")
        iniciar_execucao(
            engine,
            periodo_inicio=data_inicio,
            periodo_fim=data_fim,
        )
        atualizar_periodo(engine, data_inicio, data_fim)
        registrar_etapa(
            engine,
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

            df_temp = pd.read_sql(query, engine)

            linhas_antes = len(df_temp)
            # A verificacao e somente leitura e ocorre antes do tratamento atual.
            observar_qualidade(
                engine,
                df_temp,
                nome_df,
                nome_tabela,
                periodo_inicio=data_inicio,
                periodo_fim=data_fim,
            )
            observar_fallbacks_entrada(engine, df_temp, nome_df)
            if nome_df != 'colaboradores':
                colunas_para_ignorar = ['data_dimensao', 'data_evolucao']
                colunas_para_verificar = [col for col in df_temp.columns if col not in colunas_para_ignorar]
                df_temp = df_temp.drop_duplicates(subset=colunas_para_verificar)
                linhas_depois = len(df_temp)
                print(f" -> Tabela '{nome_df}' carregada com {linhas_depois} linhas ({linhas_antes - linhas_depois} duplicatas removidas).")
            else:
                print(f" -> Tabela '{nome_df}' carregada com {linhas_antes} linhas (tratamento de duplicatas específico será aplicado).")
            dataframes[nome_df] = df_temp
            registrar_fonte(
                engine,
                tabela_origem=nome_tabela,
                periodo_inicio=data_inicio,
                periodo_fim=data_fim,
                linhas_recebidas=linhas_antes,
                linhas_tratadas=len(df_temp),
                duplicatas=linhas_antes - len(df_temp),
                consulta=query,
            )
            registrar_etapa(
                engine,
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
                engine,
                etapa="ETL_CONSUMO",
                mensagem=f"Falha ao carregar a tabela {nome_tabela}: {e}",
                excecao=e,
            )
            return None

    # A camada de identidade observa o conjunto bruto e nunca devolve dados ao calculo.
    observar_identidades(engine, dataframes)

    if 'colaboradores' in dataframes:
        print("\n-> Aplicando tratamento especial na tabela de colaboradores...")
        df_colaboradores = dataframes['colaboradores']

        df_colaboradores['data_evolucao'] = pd.to_datetime(df_colaboradores['data_evolucao'], errors='coerce')
        data_evolucao_mais_recente = df_colaboradores['data_evolucao'].max()
        linhas_antes_evolucao = len(df_colaboradores)
        df_colaboradores = df_colaboradores[df_colaboradores['data_evolucao'] == data_evolucao_mais_recente].copy()
        print(f"   - Filtro data_evolucao: mantidos {len(df_colaboradores)} de {linhas_antes_evolucao} registros.")

        linhas_antes_ativo = len(df_colaboradores)
        df_colaboradores = df_colaboradores[df_colaboradores['usuario_ativo'].str.strip().str.lower() == 'sim'].copy()
        print(f"   - Filtro usuario_ativo: mantidos {len(df_colaboradores)} de {linhas_antes_ativo} registros.")

        df_colaboradores['data_dimensao'] = pd.to_datetime(df_colaboradores['data_dimensao'], errors='coerce')
        df_colaboradores = df_colaboradores.sort_values(by='data_dimensao', ascending=False)

        linhas_antes = len(df_colaboradores)
        df_colaboradores = df_colaboradores.drop_duplicates(subset=['nome_colaborador'], keep='first')
        linhas_depois = len(df_colaboradores)
        print(f"   - {linhas_antes - linhas_depois} registros de colaboradores com datas mais antigas foram removidos.")

        df_colaboradores = df_colaboradores.reset_index(drop=True)
        print(f"   - Índice resetado. Tabela final com {linhas_depois} colaboradores únicos e mais recentes.")

        dataframes['colaboradores'] = df_colaboradores
        observar_fallback_jornada(engine, df_colaboradores)
        registrar_etapa(
            engine,
            etapa="TRATAMENTO_ENTRADA",
            status="CONCLUIDA",
            origem="INVOLVES_BRACELL",
            tabela_origem="colaboradores_ativos_bracell",
            linhas_recebidas=linhas_antes_evolucao,
            linhas_tratadas=len(df_colaboradores),
            mensagem="Tratamento legado de colaboradores concluido sem alteracao de regra.",
        )

    print("-" * 30)
    registrar_etapa(
        engine,
        etapa="ETL_CONSUMO",
        status="CONCLUIDA",
        origem="INVOLVES_BRACELL",
        linhas_recebidas=sum(len(df) for df in dataframes.values()),
        mensagem="Consumo e tratamento de entrada concluidos.",
    )
    return dataframes, engine
