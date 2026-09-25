import json
from collections import Counter
from audit_architecture import engine
from sqlalchemy import text

with engine().connect() as c:
    print(json.dumps([dict(r) for r in c.exec_driver_sql("SELECT e.execution_id,e.versao_aplicacao,e.periodo_inicio,e.periodo_fim, "
        "o.tipo_problema,o.colaborador,COUNT(*) n FROM pdoh_controle.execucao e JOIN pdoh_controle.oportunidade o "
        "ON o.execution_id=e.execution_id WHERE o.tipo_problema='INCONSISTENCIA_HORARIO' "
        "AND o.tabela_origem='relatorio_checkin_bracell' GROUP BY 1,2,3,4,5,6").mappings()],default=str))
    for kind in ('DADO_FORA_DO_PADRAO','INCONSISTENCIA_HORARIO','CAMPO_OBRIGATORIO_VAZIO','CHECKOUT_AUSENTE'):
        rows = c.execute(text('SELECT tabela_origem,evidencia FROM pdoh_controle.oportunidade '
            'WHERE tipo_problema=:kind'), dict(kind=kind)).mappings().all()
        counts, examples = Counter(), {}
        for row in rows:
            ev = json.loads(row['evidencia']) if isinstance(row['evidencia'],str) else row['evidencia'] or {}
            field = ev.get('campo_esperado',ev.get('campo',ev.get('coluna',ev.get('campo_inicio'))))
            key = str((row['tabela_origem'],field))
            counts[key] += 1
            examples.setdefault(key,ev)
        print(json.dumps(dict(kind=kind, counts=dict(counts), examples=examples),ensure_ascii=True,default=str))
