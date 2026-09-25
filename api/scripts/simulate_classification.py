"""Simulação integral SELECT-only no controle; não aplica as propostas."""
import json
from collections import Counter, defaultdict
from api.app.config import Settings
from api.app.database import Database
from api.app.alerts import evidence_fields, evidence_object
from api.app.research import research_assessment

expected_names = {'CAMILA RUFINO DE OLIVEIRA', 'EDGARD JOAO CUTRIM DINIZ', 'GERSON DA SILVA GOMES'}
db = Database(Settings.load())
db.initialize()
try:
    with db.connection() as connection:
        counts, transitions, issues = Counter(), Counter(), Counter()
        uf_groups, examples, research_fields = {}, defaultdict(list), Counter()
        rules = {row['regra_id']: dict(row) for row in connection.exec_driver_sql('SELECT * FROM pdoh_controle.regra_tratativa').mappings()}
        query = connection.exec_driver_sql('SELECT oportunidade_id, marca, regra_id, tipo_problema, evidencia, origem, tabela_origem, colaborador, execution_id FROM pdoh_controle.oportunidade ORDER BY oportunidade_id').mappings()
        expected_name_rows = Counter()
        for row in query:
            rule = rules.get(row['regra_id'])
            valid_link = rule and rule['tipo_problema'] == row['tipo_problema'] and rule['marca'] in (None, row['marca'])
            current = rule['classificacao'] if valid_link else 'SEM_CLASSIFICACAO'
            counts[current] += 1
            if not row['regra_id']: issues['sem_regra_id'] += 1
            elif not rule: issues['regra_inexistente'] += 1
            elif not valid_link: issues['regra_marca_ou_tipo_divergente'] += 1
            if not row['marca']: issues['sem_marca'] += 1
            if not row['origem']: issues['sem_origem'] += 1
            evidence = evidence_object(row['evidencia'])
            if not evidence: issues['sem_evidencia_estruturada'] += 1
            fields = evidence_fields(evidence)
            name = (row['colaborador'] or '').strip().upper()
            if name in expected_names: expected_name_rows[name] += 1
            is_uf = row['marca']=='BRACELL' and any(field.strip().lower()=='uf' for field in fields)
            if is_uf:
                key = (name or 'SEM_COLABORADOR', current, row['tipo_problema'])
                item = uf_groups.setdefault(key, dict(colaborador=name or None, classificacao_atual=current, tipo=row['tipo_problema'], ocorrencias=0, exemplo=dict(row)))
                item['ocorrencias'] += 1
            assessments = research_assessment(row)
            for item in assessments: research_fields[item['campo']] += 1
            # Simulação somente dos casos com evidência e vínculo já reconhecido.
            if assessments and valid_link:
                targets = {item['classificacao_sugerida'] for item in assessments}
                target = 'OPORTUNIDADE' if 'OPORTUNIDADE' in targets else 'ALERTA' if 'ALERTA' in targets else 'TELEMETRIA'
                if target != current:
                    transition = f'{current} -> {target}'
                    transitions[transition] += 1
                    if len(examples[transition]) < 3:
                        examples[transition].append(dict(id=row['oportunidade_id'], regra_id=row['regra_id'], marca=row['marca'], tipo=row['tipo_problema'], origem=row['origem'], tabela=row['tabela_origem'], evidencia=evidence))
        after = counts.copy()
        for transition, quantity in transitions.items():
            old, new = transition.split(' -> ')
            after[old] -= quantity; after[new] += quantity
        history_count = connection.exec_driver_sql('SELECT COUNT(*) FROM pdoh_controle.oportunidade_historico').scalar()
        print(json.dumps(dict(modo='SIMULACAO_SEM_ESCRITA', contagens_atuais=counts, contagens_propostas=after,
            transicoes=transitions, exemplos=examples, validacoes=issues, uf_grupos=list(uf_groups.values()),
            nomes_esperados_no_historico=expected_name_rows, pesquisa_por_campo=research_fields,
            historico_preservado_quantidade=history_count), ensure_ascii=False, default=str, indent=2))
finally:
    db.close()
