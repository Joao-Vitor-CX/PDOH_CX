"""Diagnóstico SELECT-only; executar no runtime da API. Não carrega o pipeline."""
import json
from collections import Counter, defaultdict
from api.app.config import Settings
from api.app.database import Database

db = Database(Settings.load())
db.initialize()  # inclusive validação de privilégios SELECT-only
try:
    with db.connection() as connection:
        counts = [dict(row) for row in connection.exec_driver_sql(
            "SELECT r.classificacao, COUNT(*) total, COUNT(o.colaborador_id_interno) com_id "
            "FROM pdoh_controle.oportunidade o LEFT JOIN pdoh_controle.regra_tratativa r "
            "ON o.regra_id=r.regra_id AND o.tipo_problema=r.tipo_problema GROUP BY r.classificacao"
        ).mappings()]
        fields = Counter()
        samples = defaultdict(list)
        query = connection.exec_driver_sql(
            "SELECT oportunidade_id, evidencia, execution_id FROM pdoh_controle.oportunidade "
            "WHERE tipo_problema='PESQUISA_CAMPOS_NULOS' ORDER BY oportunidade_id"
        ).mappings()
        for row in query:
            evidence = row['evidencia']
            if isinstance(evidence, str):
                evidence = json.loads(evidence)
            evidence = evidence if isinstance(evidence, dict) else {}
            names = evidence.get('campo_esperado', evidence.get('campo', []))
            names = names if isinstance(names, list) else [names]
            for name in set(str(n) for n in names):
                fields[name] += 1
                if len(samples[name]) < 1:
                    samples[name].append(dict(id=row['oportunidade_id'], execution_id=row['execution_id'], registro=evidence.get('registro_afetado'), encontrado=evidence.get('valor_encontrado')))
        unchanged = {}
        for table in ('oportunidade', 'oportunidade_historico', 'de_para_historico', 'execucao'):
            unchanged[table] = connection.exec_driver_sql('SELECT COUNT(*) FROM pdoh_controle.' + table).scalar()
        print(json.dumps(dict(classificacoes=counts, pesquisa_por_campo=dict(fields), exemplos=dict(samples), contagens=unchanged), ensure_ascii=False, default=str, indent=2))
finally:
    db.close()
