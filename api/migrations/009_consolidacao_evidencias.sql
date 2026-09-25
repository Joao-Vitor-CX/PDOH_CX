-- Somente configuração de evidência e NOVA regra. Histórico/classificações existentes intactos.
UPDATE pdoh_controle.configuracao_evidencia_regra
SET criterios=JSON_ARRAY('colaborador_vigente','dia_trabalhado','jornada_resolvida','sem_abono','houve_entrada')
WHERE tipo_problema IN ('CHECKOUT_AUSENTE','INCONSISTENCIA_HORARIO');

INSERT INTO pdoh_controle.regra_tratativa
(regra_id,marca,tipo_problema,classificacao,titulo,titulo_exibicao,impacto_negocio,acao_recomendada,
 severidade_padrao,descricao_cenario,regra_identificacao,tratamento_esperado,acao_aplicacao,
 prioridade,responsavel_padrao,origem,campo_afetado,criterios_operacionais)
SELECT UUID(), e.marca,'CHECKIN_ENTRADA_AUSENTE','OPORTUNIDADE','Entrada não registrada',
 'Entrada não registrada','Jornada','Validar o registro de entrada com o colaborador.',
 'MEDIA','Entrada ausente no dia previsto, comprovada na fonte oficial.',
 'Evidence engine: ativo, jornada válida, roteiro, sem abono, entrada ausente.',
 'Validar o registro de entrada na origem.','ALERTAR',60,'Lider da operacao',
 'Fonte identificada na matriz','primeiro_checkin',JSON_OBJECT()
FROM (SELECT DISTINCT marca FROM pdoh_controle.configuracao_evidencia_regra
      WHERE tipo_problema='CHECKIN_ENTRADA_AUSENTE') e
WHERE NOT EXISTS (SELECT 1 FROM pdoh_controle.regra_tratativa r
                  WHERE r.marca=e.marca AND r.tipo_problema='CHECKIN_ENTRADA_AUSENTE');
