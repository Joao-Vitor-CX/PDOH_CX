import { useCallback } from 'react';
import {
  BadgeCheck,
  CalendarDays,
  CircleHelp,
  Clock3,
  Database,
  History,
  Lightbulb,
  ShieldCheck,
  UserRound,
} from 'lucide-react';
import { ConsultationState } from '@/components/platform/consultation-ui';
import { usePdohResource } from '@/src/hooks/use-pdoh-resource';
import { formatDate, formatDateTime, formatNumber, formatPeriod } from '@/src/lib/pdoh-format';
import { displayLabel } from '@/src/lib/operational-display';
import {
  loadGroupEvidence,
  type GroupEvidence,
  type OperationalFilters,
  type OperationalGroup,
} from '@/src/services/operational-api';
import { queryString } from '@/src/services/pdoh-api';
import { journeyOriginLabel, loadOpportunityTrace, type OccurrenceTrace } from '@/src/services/operational-trace';

/** Tom de cada resultado. Indisponível nunca é verde: é ausência de prova. */
const RESULTADO = {
  confirmado: {
    tom: 'border-emerald-200 bg-emerald-50 text-emerald-900',
    Icon: BadgeCheck,
    resumo: 'A ocorrência foi comprovada na fonte oficial.',
  },
  nao_aplicavel: {
    tom: 'border-slate-200 bg-slate-50 text-slate-700',
    Icon: ShieldCheck,
    resumo: 'O registro existe, mas não é cobrança operacional.',
  },
  indisponivel: {
    tom: 'border-amber-200 bg-amber-50 text-amber-900',
    Icon: CircleHelp,
    resumo: 'Não foi possível comprovar a ocorrência na fonte oficial.',
  },
} as const;

function evidenceByKey(groupId: string, key: string, signal: AbortSignal) {
  return loadGroupEvidence(groupId, Object.fromEntries(new URLSearchParams(key)), signal);
}

function Campo({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <div>
      <dt className="text-xs font-semibold text-slate-500">{rotulo}</dt>
      <dd className="mt-0.5 break-words text-sm text-slate-900">{valor}</dd>
    </div>
  );
}

/** Frase única que responde "o que aconteceu?" sem jargão de banco. */
function resumoDoCaso(dados: GroupEvidence) {
  const campo = dados.fonte.campo || dados.oportunidade.campo;
  const quem = dados.oportunidade.colaborador || 'o colaborador';
  const rotulo = campo ? displayLabel(campo).toLocaleLowerCase('pt-BR') : 'o campo analisado';
  return `Na fonte oficial da operação, ${rotulo} de ${quem} não atendeu ao esperado em ${formatNumber(dados.oportunidade.quantidade)} ocorrência(s) do período.`;
}

const VALIDACAO: Record<string, string> = {
  confirmado: 'Confirmado na fonte oficial',
  nao_aplicavel: 'Não aplicável (exceção)',
  indisponivel: 'Sem comprovação',
};

function OccurrenceCard({ ocorrencia }: { ocorrencia: OccurrenceTrace }) {
  return (
    <li className="rounded-xl border border-slate-200 p-4 text-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <strong className="text-slate-900">{formatDate(ocorrencia.data)}</strong>
        <span className="text-xs text-slate-500">{VALIDACAO[ocorrencia.validacao] ?? displayLabel(ocorrencia.validacao)}</span>
      </div>
      <p className="mt-2 text-slate-700"><span className="font-semibold">Cenário identificado: </span>{ocorrencia.cenario}</p>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
        <Campo rotulo="Jornada considerada" valor={ocorrencia.jornada ?? 'Não informada'} />
        <Campo rotulo="Origem da jornada" valor={journeyOriginLabel(ocorrencia.jornada_origem) ?? 'Não informada'} />
        <Campo rotulo="Fallback aplicado" valor={ocorrencia.fallback === null ? 'Não identificado' : ocorrencia.fallback ? 'Sim' : 'Não'} />
        <Campo rotulo="Motivo" valor={ocorrencia.motivo ?? '—'} />
        <Campo rotulo="Fonte da jornada" valor={ocorrencia.fonte_jornada ?? 'Não informada'} />
        <Campo rotulo="Fonte da evidência" valor={ocorrencia.fonte_evidencia ?? 'Não informada'} />
      </dl>
      {ocorrencia.referencia_jornada === 'resolucao_da_data' && (
        <p className="mt-2 text-[11px] text-slate-500">
          A prova desta ocorrência não registrou as horas; a jornada exibida é a resolução oficial da data.
        </p>
      )}
      <p className="mt-3 flex flex-wrap items-center gap-x-2 text-[11px] text-slate-500">
        <History className="size-3" aria-hidden="true" />
        Identificada em {formatDateTime(ocorrencia.historico.identificada_em)} · execução {ocorrencia.historico.execucao}
        {ocorrencia.historico.repeticoes > 1 && ` · gravada em ${formatNumber(ocorrencia.historico.repeticoes)} execuções`}
      </p>
    </li>
  );
}

function OccurrenceTraceList({ group, window }: { group: OperationalGroup; window: OperationalFilters }) {
  const key = `trace|${group.grupo_id}|${queryString(window as Record<string, string | undefined>)}`;
  const loader = useCallback((signal: AbortSignal) => loadOpportunityTrace(group, window, signal), [group, window]);
  const resource = usePdohResource(key, loader);
  return (
    <ConsultationState {...resource} hasData={!!resource.data}>
      {resource.data && (resource.data.length ? (
        <ul className="mt-3 space-y-2">
          {resource.data.map((ocorrencia, indice) => (
            <OccurrenceCard key={`${ocorrencia.data}-${indice}`} ocorrencia={ocorrencia} />
          ))}
        </ul>
      ) : <p className="mt-3 text-sm text-slate-500">Nenhuma ocorrência nesta janela.</p>)}
    </ConsultationState>
  );
}

/**
 * Modal operacional da oportunidade.
 *
 * Tudo vem de GET /api/v2/oportunidades/{grupo_id}/evidencias: o navegador não agrupa,
 * não conta, não classifica e não deduz. Quando o backend diz que a evidência está
 * indisponível, a tela diz o mesmo — nunca apresenta ausência de prova como confirmação.
 */
export function OpportunityDetail({
  group,
  window,
}: {
  group: OperationalGroup;
  window: OperationalFilters;
}) {
  const key = queryString(window as Record<string, string | undefined>);
  const loader = useCallback(
    (signal: AbortSignal) => evidenceByKey(group.grupo_id, key, signal),
    [group.grupo_id, key],
  );
  const resource = usePdohResource(`${group.grupo_id}|${key}`, loader);
  const dados = resource.data;
  const estilo = dados ? RESULTADO[dados.validacao.resultado] : null;

  return (
    <div className="space-y-5">
      {/* Cabeçalho: regra, colaborador e período — nada técnico. */}
      <header className="space-y-2">
        <p className="flex items-start gap-2 text-sm text-slate-700">
          <UserRound className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <span className="break-words font-medium">
            {group.colaborador || 'Colaborador não informado'}
          </span>
        </p>
        <p className="flex items-center gap-2 text-sm text-slate-600">
          <CalendarDays className="size-4 shrink-0" aria-hidden="true" />
          {formatPeriod(group.primeira_ocorrencia, group.ultima_ocorrencia)}
        </p>
        <p className="flex items-center gap-2 text-sm text-slate-600">
          <ShieldCheck className="size-4 shrink-0" aria-hidden="true" />
          Regra responsável: <strong className="font-semibold text-slate-800">{group.tipo_problema}</strong> ({group.titulo})
        </p>
      </header>

      <ConsultationState {...resource} hasData={!!dados}>
        {dados && estilo && (
          <>
            {/* 1. O que aconteceu */}
            <section className="rounded-xl bg-slate-50 p-4">
              <h3 className="text-sm font-bold text-slate-900">O que aconteceu</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-700">
                {resumoDoCaso(dados)}
              </p>
              <dl className="mt-4 grid grid-cols-2 gap-4">
                <Campo
                  rotulo="Ocorrências"
                  valor={formatNumber(dados.oportunidade.quantidade)}
                />
                <Campo
                  rotulo="Impacto"
                  valor={dados.oportunidade.impacto || 'Não informado'}
                />
              </dl>
            </section>

            {/* 2. Validação: o veredito antes da prova, para não induzir leitura. */}
            <section className={`rounded-xl border p-4 ${estilo.tom}`}>
              <h3 className="flex items-center gap-2 text-sm font-bold">
                <estilo.Icon className="size-4" aria-hidden="true" />
                {dados.validacao.rotulo}
              </h3>
              <p className="mt-2 text-sm leading-relaxed">
                {dados.validacao.motivo || estilo.resumo}
              </p>
              <p className="mt-3 text-xs opacity-80">
                {formatNumber(dados.validacao.ocorrencias_comprovadas)} de{' '}
                {formatNumber(dados.validacao.ocorrencias_avaliadas)} ocorrência(s) com
                comprovação ·{' '}
                {dados.validacao.jornada_origem === 'INDISPONIVEL'
                  ? 'jornada não apurada'
                  : `jornada apurada por ${displayLabel(dados.validacao.jornada_origem)}`}
              </p>
            </section>

            {/* 3. Evidência: de onde veio o dado. */}
            <section>
              <h3 className="flex items-center gap-2 text-sm font-bold text-slate-900">
                <Database className="size-4" aria-hidden="true" />
                Evidência
              </h3>
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border border-slate-200 p-4">
                <Campo
                  rotulo="Fonte"
                  valor={
                    dados.regra_aplicada?.fonte ||
                    (dados.fonte.tabela ? displayLabel(dados.fonte.tabela) : 'Não informada')
                  }
                />
                <Campo
                  rotulo="Campo analisado"
                  valor={dados.fonte.campo ? displayLabel(dados.fonte.campo) : 'Não informado'}
                />
                <Campo
                  rotulo="Esperado"
                  valor={dados.fonte.valor_esperado || 'Não cadastrado para esta regra'}
                />
                <Campo
                  rotulo="Encontrado"
                  valor={
                    dados.ocorrencias[0]?.valor_encontrado ||
                    dados.evidencias.find((linha) => linha.valor_encontrado)?.valor_encontrado ||
                    'Não localizado'
                  }
                />
              </dl>

              {dados.evidencias.length > 0 && (
                <ul className="mt-3 space-y-2">
                  {dados.evidencias.map((linha, indice) => (
                    <li
                      key={`${linha.validacao}-${indice}`}
                      className="flex items-start gap-3 rounded-lg border border-slate-200 p-3 text-sm"
                    >
                      <span
                        aria-hidden="true"
                        className={`mt-1 size-2 shrink-0 rounded-full ${
                          linha.atendido === true
                            ? 'bg-emerald-500'
                            : linha.atendido === false
                              ? 'bg-slate-400'
                              : 'bg-amber-500'
                        }`}
                      />
                      <div className="min-w-0">
                        <p className="font-medium text-slate-800">
                          {displayLabel(linha.validacao)}
                          <span className="ml-2 text-xs font-normal text-slate-500">
                            {linha.atendido === true
                              ? 'comprovado'
                              : linha.atendido === false
                                ? 'não atendido'
                                : 'não verificável'}
                          </span>
                        </p>
                        <p className="mt-0.5 text-xs leading-relaxed text-slate-600">
                          {linha.valor_esperado || 'Sem descrição cadastrada.'}
                        </p>
                        {(linha.fonte || linha.campo) && (
                          <p className="mt-1 text-xs text-slate-500">
                            {linha.fonte ? displayLabel(linha.fonte) : 'origem não informada'}
                            {linha.campo ? ` · ${displayLabel(linha.campo)}` : ''}
                            {linha.valor_encontrado ? ` · ${linha.valor_encontrado}` : ''}
                          </p>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* 4. Por que apareceu, ocorrência a ocorrência: cenário, jornada, fallback, fonte e histórico. */}
            <section>
              <h3 className="flex items-center gap-2 text-sm font-bold text-slate-900">
                <Clock3 className="size-4" aria-hidden="true" />
                Por que esta oportunidade apareceu
              </h3>
              <OccurrenceTraceList group={group} window={window} />
            </section>

            {/* 5. Tratativa. */}
            <section className="rounded-xl border border-blue-200 bg-blue-50 p-4">
              <h3 className="flex items-center gap-2 text-sm font-bold text-blue-950">
                <Lightbulb className="size-4" aria-hidden="true" />
                Tratativa
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-blue-950">
                {dados.tratamento.acao_recomendada ||
                  'Orientação ainda não cadastrada para esta regra.'}
              </p>
              {dados.tratamento.responsavel && (
                <p className="mt-2 text-xs text-blue-900">
                  Responsável: {dados.tratamento.responsavel}
                </p>
              )}
            </section>
          </>
        )}
      </ConsultationState>
    </div>
  );
}
