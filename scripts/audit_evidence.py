"""Auditoria somente leitura; nunca executa ETL nem grava/reclassifica histórico."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'bracell')]
from dotenv import dotenv_values
from sqlalchemy import text
from audit_architecture import engine
from src.database import criar_engine_origem
from src.evidence_context import (carregar_matriz, carregar_status_day, carregar_checkins,
    indexar_jornada, comprovar, justificativas_abonaveis)
from src.journey_observer import resolve_official
from src.operational_detectors import detectar_entrada_ausente
from shared.evidence_engine import _vazio
import pandas as pd

TIPOS = ('CHECKOUT_AUSENTE', 'CHECKIN_ENTRADA_AUSENTE', 'INCONSISTENCIA_HORARIO')


def _lacuna(prova):
    """Qual fonte, qual campo e qual contexto faltaram — sem mascarar a ausência."""
    pendente = next((v for v in prova.get('verificacoes') or ()
                     if v.get('atendido') is None), None)
    if pendente is None:
        return dict(fonte_faltante=prova.get('fonte'), campo_faltante=prova.get('campo'),
                    contexto_nao_encontrado=prova.get('motivo'), criterio=None)
    return dict(fonte_faltante=pendente.get('fonte') or prova.get('fonte'),
                campo_faltante=pendente.get('campo') or prova.get('campo'),
                contexto_nao_encontrado=pendente.get('descricao'),
                criterio=pendente.get('criterio'))


def detalhar(items, resultado):
    """Uma linha por ocorrência, com a lacuna exata. Limitado para não virar dump."""
    saida = []
    for item in items:
        prova = item['evidencia']['comprovacao']
        if prova['resultado'] != resultado:
            continue
        saida.append(dict(colaborador=prova.get('colaborador'), data=prova.get('data'),
                          regra=prova.get('regra'), motivo=prova.get('motivo'),
                          jornada_origem=prova.get('jornada_origem'), **_lacuna(prova)))
    return sorted(saida, key=lambda r: (str(r['data']), str(r['colaborador'])))[:200]


def resumo(items):
    provas = [i['evidencia']['comprovacao'] for i in items]
    counts = Counter(p['resultado'] for p in provas)
    return dict(total_analisado=len(provas), **{k: counts[k] for k in
        ('confirmado', 'nao_aplicavel', 'indisponivel')}, motivos_descartes=dict(Counter(
        p['motivo'] for p in provas if p['resultado'] != 'confirmado')),
        detalhe_indisponiveis=detalhar(items, 'indisponivel'),
        detalhe_nao_aplicaveis=detalhar(items, 'nao_aplicavel'))


def auditar(local, source, inicio, fim):
    matriz, regras = carregar_matriz(local)
    status = carregar_status_day(source, matriz, periodo_inicio=inicio, periodo_fim=fim)
    registros = carregar_checkins(source, matriz, periodo_inicio=inicio, periodo_fim=fim)
    jornadas = {}
    for dia in pd.date_range(inicio, fim):
        data = str(dia.date())
        for nome, row in indexar_jornada(resolve_official(local, source, as_of=data)).items():
            jornadas[(nome, data)] = row
    with local.connect() as c:
        c.exec_driver_sql('SET SESSION TRANSACTION READ ONLY')
        existentes = [dict(r) for r in c.execute(text(
            "SELECT o.* FROM pdoh_controle.oportunidade o JOIN pdoh_controle.execucao e "
            "ON e.execution_id=o.execution_id WHERE o.marca='BRACELL' AND e.operacao='EXCLUSIVA' "
            "AND o.data_referencia BETWEEN :inicio AND :fim "
            "AND o.tipo_problema IN ('CHECKOUT_AUSENTE','CHECKIN_ENTRADA_AUSENTE','INCONSISTENCIA_HORARIO') "
            "AND NOT EXISTS (SELECT 1 FROM pdoh_controle.execucao_contexto x "
            "WHERE x.execution_id=o.execution_id AND x.finalidade='VALIDACAO')"),
            dict(inicio=inicio, fim=fim)).mappings()]
    for row in existentes:
        if isinstance(row.get('evidencia'), str):
            row['evidencia'] = json.loads(row['evidencia'])
    novos = detectar_entrada_ausente(pd.DataFrame([r for r in (status or {}).values() if r]))
    fonte = matriz.tabela('checkin') if matriz else None
    for (nome, data), rows in (registros or {}).items():
        for row in rows:
            base = dict(marca='BRACELL', colaborador=row['colaborador'], data_referencia=data,
                        origem='INVOLVES', tabela_origem=fonte)
            if (_vazio(row.get('hora_saida')) and not _vazio(row.get('hora_entrada')) and
                    all(_vazio(row.get(c)) for c in ('checkout_sistema','checkout_registrado'))):
                novos.append(dict(base, tipo_problema='CHECKOUT_AUSENTE', evidencia={}))
            if not _vazio(row.get('hora_entrada')) and not _vazio(row.get('hora_saida')):
                inicio_h = pd.to_datetime(str(row['hora_entrada']), errors='coerce')
                fim_h = pd.to_datetime(str(row['hora_saida']), errors='coerce')
                if pd.notna(inicio_h) and pd.notna(fim_h) and fim_h < inicio_h:
                    novos.append(dict(base, tipo_problema='INCONSISTENCIA_HORARIO', evidencia={
                        'valor_inicio': str(row['hora_entrada']), 'valor_fim': str(row['hora_saida'])}))
    # Grain da auditoria nova: uma ocorrência por regra/colaborador/dia/par observado.
    novos = list({(r['tipo_problema'], r['colaborador'], str(r['data_referencia'])[:10],
                   json.dumps(r['evidencia'], sort_keys=True)): r for r in novos}.values())
    def avaliar_lote(rows):
        ok, no = comprovar(None, rows, matriz=matriz, regras=regras, status_day=status,
                          jornada=jornadas, abonaveis=justificativas_abonaveis(),
                          registros_origem=registros, registrar=False)
        return ok + no
    historicos, candidatos = avaliar_lote(existentes), avaliar_lote(novos)
    cobertura = dict(
        status_day_linhas=len([r for r in (status or {}).values() if r]),
        status_day_consultado=status is not None,
        checkin_pares_colaborador_dia=len(registros or {}),
        checkin_linhas=sum(len(v) for v in (registros or {}).values()),
        jornadas_resolvidas=len(jornadas))
    return dict(periodo=dict(inicio=inicio, fim=fim), somente_leitura=True, cobertura_fonte=cobertura,
        metodologia='Antes: registros históricos, incluindo repetições entre execuções. Depois: revalidação dos mesmos registros. Candidatos atuais: regra/colaborador/dia/par; não comparar diretamente com o histórico.',
        regras={tipo: dict(antes=sum(r['tipo_problema'] == tipo for r in existentes),
            depois=resumo([r for r in historicos if r['tipo_problema'] == tipo]),
            candidatos_atuais=resumo([r for r in candidatos if r['tipo_problema'] == tipo])) for tipo in TIPOS})


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--inicio', default='2026-08-31')
    parser.add_argument('--fim', default='2026-09-05')
    parser.add_argument('--output', default=str(ROOT / 'artifacts/evidence-audit.json'))
    args = parser.parse_args()
    os.environ.update({k: v for k, v in dotenv_values(ROOT / '.env.cadastro').items() if v is not None})
    report = auditar(engine(), criar_engine_origem(), args.inicio, args.fim)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, default=str))


if __name__ == '__main__':
    main()
