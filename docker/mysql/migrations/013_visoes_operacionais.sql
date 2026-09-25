-- Intuitive read models. Historical physical tables keep their names and foreign keys.
CREATE OR REPLACE SQL SECURITY INVOKER VIEW pdoh_controle.regras_negocio AS
SELECT * FROM pdoh_controle.regra_tratativa;
CREATE OR REPLACE SQL SECURITY INVOKER VIEW pdoh_controle.oportunidades_historicas AS
SELECT * FROM pdoh_controle.oportunidade;
CREATE OR REPLACE SQL SECURITY INVOKER VIEW pdoh_controle.alertas_historicos AS
SELECT * FROM pdoh_controle.alerta;
CREATE OR REPLACE SQL SECURITY INVOKER VIEW pdoh_controle.configuracoes_governanca AS
SELECT * FROM pdoh_controle.regra_tratativa WHERE classificacao='CONFIGURACAO';
CREATE OR REPLACE SQL SECURITY INVOKER VIEW pdoh_controle.achados_classificados AS
WITH historico AS (SELECT 'oportunidade' origem_registro, oportunidade_id registro_id,execution_id,marca,tipo_problema,colaborador,colaborador_id_interno,tabela_origem,data_referencia,fingerprint,evidencia,identificada_em FROM pdoh_controle.oportunidade
UNION ALL
SELECT 'alerta' origem_registro, alerta_id registro_id,execution_id,marca,tipo_problema,colaborador,colaborador_id_interno,tabela_origem,data_referencia,fingerprint,evidencia,identificada_em FROM pdoh_controle.alerta),
catalogado AS (
 SELECT h.*,e.operacao,COALESCE(x.finalidade,'OPERACIONAL') finalidade,r.regra_id,
 r.titulo_exibicao,r.responsavel_padrao,r.criterios_operacionais,
 CASE WHEN r.origem_excecao=h.tabela_origem THEN r.impacto_negocio_excecao ELSE r.impacto_negocio END impacto,
 CASE WHEN r.origem_excecao=h.tabela_origem THEN r.acao_recomendada_excecao ELSE r.acao_recomendada END acao_recomendada,
 CASE WHEN r.origem_excecao=h.tabela_origem THEN r.classificacao_excecao ELSE r.classificacao END classe_catalogo,
 COALESCE(JSON_UNQUOTE(JSON_EXTRACT(h.evidencia,'$.campo_esperado')),
 JSON_UNQUOTE(JSON_EXTRACT(h.evidencia,'$.campo')),JSON_UNQUOTE(JSON_EXTRACT(h.evidencia,'$.campo_origem')),
 JSON_UNQUOTE(JSON_EXTRACT(h.evidencia,'$.coluna')),
 CONCAT_WS('+',JSON_UNQUOTE(JSON_EXTRACT(h.evidencia,'$.campo_inicio')),JSON_UNQUOTE(JSON_EXTRACT(h.evidencia,'$.campo_fim')))) campo
 FROM historico h JOIN pdoh_controle.execucao e ON e.execution_id=h.execution_id AND e.marca=h.marca
 LEFT JOIN pdoh_controle.execucao_contexto x ON x.execution_id=e.execution_id AND x.marca=e.marca
 LEFT JOIN pdoh_controle.regra_tratativa r ON r.regra_id=(
 SELECT r2.regra_id FROM pdoh_controle.regra_tratativa r2 WHERE r2.status_regra='ATIVA'
 AND r2.tipo_problema=h.tipo_problema AND (r2.marca=h.marca OR r2.marca IS NULL)
 ORDER BY (r2.marca IS NULL),r2.prioridade,r2.regra_id LIMIT 1)
)
SELECT h.*,COALESCE(v.classificacao,
 CASE WHEN h.classe_catalogo='OPORTUNIDADE' AND (
 NULLIF(TRIM(h.impacto),'') IS NULL OR NULLIF(TRIM(h.acao_recomendada),'') IS NULL
 OR NULLIF(TRIM(h.responsavel_padrao),'') IS NULL
 OR (NULLIF(TRIM(h.colaborador),'') IS NULL AND h.colaborador_id_interno IS NULL)
 OR (JSON_EXTRACT(h.criterios_operacionais,'$.evidencia') IS NOT NULL AND
 COALESCE(JSON_CONTAINS(h.evidencia,JSON_EXTRACT(h.criterios_operacionais,'$.evidencia')),0)=0))
 THEN 'ALERTA' ELSE h.classe_catalogo END) classificacao,
 v.motivo motivo_revisao
FROM catalogado h LEFT JOIN pdoh_controle.achado_revisao v ON v.id=(
 SELECT MAX(v2.id) FROM pdoh_controle.achado_revisao v2 WHERE v2.registro_id=h.registro_id
 AND v2.origem_registro=h.origem_registro AND v2.marca=h.marca AND v2.execution_id=h.execution_id);

CREATE OR REPLACE SQL SECURITY INVOKER VIEW pdoh_controle.oportunidades_operacionais AS
SELECT marca,operacao,tipo_problema,regra_id,colaborador_id_interno,
 MAX(colaborador) colaborador,
 tabela_origem,campo,MAX(titulo_exibicao) titulo,MAX(impacto) impacto,
 MAX(acao_recomendada) acao_recomendada,MAX(responsavel_padrao) responsavel,
 COUNT(DISTINCT fingerprint) ocorrencias_distintas,COUNT(*) registros_historicos,
 MIN(data_referencia) primeira_ocorrencia,MAX(data_referencia) ultima_ocorrencia
FROM pdoh_controle.achados_classificados WHERE classificacao='OPORTUNIDADE' AND finalidade='OPERACIONAL'
GROUP BY marca,operacao,tipo_problema,regra_id,colaborador_id_interno,
 CASE WHEN colaborador_id_interno IS NULL THEN colaborador ELSE NULL END,tabela_origem,campo;

CREATE OR REPLACE SQL SECURITY INVOKER VIEW pdoh_controle.alertas_qualidade AS
SELECT marca,operacao,tipo_problema,regra_id,colaborador_id_interno,
 MAX(colaborador) colaborador,
 tabela_origem,campo,MAX(titulo_exibicao) titulo,MAX(impacto) impacto,
 MAX(acao_recomendada) acao_recomendada,MAX(responsavel_padrao) responsavel,
 COUNT(DISTINCT fingerprint) ocorrencias_distintas,COUNT(*) registros_historicos,
 MIN(data_referencia) primeira_ocorrencia,MAX(data_referencia) ultima_ocorrencia
FROM pdoh_controle.achados_classificados WHERE classificacao='ALERTA' AND finalidade='OPERACIONAL'
GROUP BY marca,operacao,tipo_problema,regra_id,colaborador_id_interno,
 CASE WHEN colaborador_id_interno IS NULL THEN colaborador ELSE NULL END,tabela_origem,campo;

CREATE OR REPLACE SQL SECURITY INVOKER VIEW pdoh_controle.telemetria AS
SELECT marca,operacao,execution_id,origem_registro,registro_id,tipo_problema codigo,
 evidencia,identificada_em registrado_em FROM pdoh_controle.achados_classificados
WHERE classificacao='TELEMETRIA' AND finalidade='OPERACIONAL'
UNION ALL SELECT e.marca,e.operacao,t.execution_id,'execucao_evento',CAST(t.id AS CHAR),t.codigo,t.contexto,t.ocorrido_em
FROM pdoh_controle.execucao_evento t JOIN pdoh_controle.execucao e ON e.execution_id=t.execution_id
WHERE t.categoria<>'CONFIGURACAO' AND NOT EXISTS(SELECT 1 FROM pdoh_controle.execucao_contexto x
WHERE x.execution_id=e.execution_id AND x.finalidade='VALIDACAO')
UNION ALL SELECT e.marca,e.operacao,t.execution_id,'fallback_evento',t.fallback_id,t.codigo,t.contexto,t.ocorrido_em
FROM pdoh_controle.fallback_evento t JOIN pdoh_controle.execucao e ON e.execution_id=t.execution_id
WHERE NOT EXISTS(SELECT 1 FROM pdoh_controle.execucao_contexto x
WHERE x.execution_id=e.execution_id AND x.finalidade='VALIDACAO');
