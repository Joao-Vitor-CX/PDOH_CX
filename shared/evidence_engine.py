"""Motor de evidencias: comprova por que um achado virou oportunidade.

Responsabilidade unica
    Receber um achado e o contexto ja lido das fontes oficiais e devolver a comprovacao:
    de onde veio o dado, qual campo foi analisado, o que era esperado, o que foi
    encontrado, qual regra se aplicou e quais excecoes foram consideradas.

O que este modulo NAO faz
    Nao calcula PDOH. Nao cria nem altera regra de negocio. Nao classifica achado (isso e'
    do catalogo `regra_tratativa` + `shared.operational_policy`). Nao le banco: recebe o
    contexto pronto, para poder ser exercitado sem MySQL e sem a esteira.

Tres resultados possiveis
    CONFIRMADO     todos os criterios foram comprovados na fonte oficial;
    NAO_APLICAVEL  atestado, afastamento ou justificativa abonavel cobre o dia — o achado
                   existe, mas nao e' cobranca operacional;
    INDISPONIVEL   faltou fonte, campo ou contexto. Nunca vira oportunidade e nunca vira
                   um "confirmado" por omissao.

Campo vazio nao e' prova
    Um campo nulo so sustenta oportunidade quando a regra tambem exige que o dia tenha
    sido trabalhado, que o colaborador esteja vigente e que nao haja abono. Sem esses
    criterios comprovados, o resultado e' INDISPONIVEL.
"""
from shared.evidence_config import (
    CONFIRMADO, INDISPONIVEL, JORNADA_CONFIGURACAO, JORNADA_FALLBACK, JORNADA_INDISPONIVEL,
    JORNADA_INVOLVES, JORNADA_RAW, NAO_APLICAVEL, PAPEL_COLABORADOR,
    PAPEL_STATUS_DAY,
)
from shared.journey import weekly_hours

REGRAS_OPERACIONAIS = frozenset(('CHECKOUT_AUSENTE', 'CHECKIN_ENTRADA_AUSENTE', 'INCONSISTENCIA_HORARIO'))
CRITERIOS_OBRIGATORIOS = ('colaborador_vigente', 'dia_trabalhado', 'jornada_resolvida', 'sem_abono')

# Motivos legiveis; o lider ve este texto, nao um codigo.
MOTIVO_SEM_MATRIZ = 'Não há matriz de origem cadastrada para esta marca.'
MOTIVO_SEM_REGRA = 'Não há regra de evidência cadastrada para este cenário.'
MOTIVO_SEM_FONTE = 'A fonte oficial desta regra não está configurada para a marca.'
MOTIVO_SEM_CONTEXTO = 'A fonte oficial não foi consultada nesta execução.'
MOTIVO_SEM_REGISTRO = 'Não há registro do colaborador nesta data na fonte oficial.'
MOTIVO_ABONO = 'Dia coberto por atestado, afastamento ou justificativa abonável.'
MOTIVO_SEM_JORNADA = 'A jornada do colaborador não foi resolvida em nenhuma fonte oficial.'


def _texto(valor):
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _vazio(valor):
    return _texto(valor) is None or _texto(valor).lower() in ('nan', 'nat', 'none', '(ausente)')


class Verificacao:
    """Um criterio avaliado. `atendido=None` significa 'nao foi possivel verificar'."""

    __slots__ = ('criterio', 'atendido', 'descricao', 'fonte', 'campo', 'valor')

    def __init__(self, criterio, atendido, descricao, fonte=None, campo=None, valor=None):
        self.criterio = criterio
        self.atendido = atendido
        self.descricao = descricao
        self.fonte = fonte
        self.campo = campo
        self.valor = valor

    def como_dicionario(self):
        return dict(criterio=self.criterio, atendido=self.atendido, descricao=self.descricao,
                    fonte=self.fonte, campo=self.campo, valor=self.valor)


# --------------------------------------------------------------------------- criterios
# Cada criterio recebe (registro do status day, contexto, matriz) e devolve Verificacao.
# `atendido=True` libera, `False` bloqueia (nao aplicavel) e `None` torna indisponivel.

def _colaborador_vigente(registro, contexto, matriz):
    jornada = contexto.get('jornada') or {}
    fonte = matriz.tabela(PAPEL_COLABORADOR)
    if not jornada:
        return Verificacao('colaborador_vigente', None,
                           'Cadastro do colaborador não consultado nesta execução.', fonte)
    if any(jornada.get(c) not in (True, False) for c in ('vigente', 'elegivel')):
        return Verificacao('colaborador_vigente', None, 'Elegibilidade não informada.', fonte)
    vigente = jornada['vigente'] is True and jornada['elegivel'] is True
    return Verificacao('colaborador_vigente', vigente,
                       'Colaborador ativo e com perfil operacional no cadastro oficial.'
                       if vigente else 'Colaborador inativo ou fora do perfil operacional.',
                       fonte, 'usuario_ativo', jornada.get('perfil'))


def _dia_trabalhado(registro, contexto, matriz):
    fonte = matriz.tabela(PAPEL_STATUS_DAY)
    campo = (matriz.fonte(PAPEL_STATUS_DAY).campo('roteiro') if matriz.fonte(PAPEL_STATUS_DAY)
             else None) or 'tem_roteiro'
    if registro is None:
        return Verificacao('dia_trabalhado', None, MOTIVO_SEM_REGISTRO, fonte, campo)
    valor = _texto(registro.get(campo))
    if valor is None:
        return Verificacao('dia_trabalhado', None,
                           'A fonte oficial não informa se o dia tinha roteiro.', fonte, campo)
    if valor.casefold() not in ('sim', 'true', '1', 's', 'não', 'nao', 'false', '0', 'n'):
        return Verificacao('dia_trabalhado', None, 'Status do roteiro desconhecido.', fonte, campo, valor)
    trabalhado = valor.strip().lower() in ('sim', 'true', '1', 's')
    return Verificacao('dia_trabalhado', trabalhado,
                       'Dia com roteiro previsto na operação.' if trabalhado
                       else 'Dia sem roteiro previsto: não há jornada a cobrar.',
                       fonte, campo, valor)


def _sem_abono(registro, contexto, matriz):
    """Qualquer ausencia registrada impede a oportunidade.

    Atestado, afastamento e justificativa abonavel chegam pelo mesmo campo do status day.
    A lista oficial (`Lista_justificativas_abonaveis.xlsx`) nao decide SE bloqueia -- ela
    so diz POR QUE: dentro da lista e' justificativa abonavel, fora e' afastamento ou
    atestado. Em ambos os casos nao ha jornada a cobrar do colaborador.
    """
    fonte_status = matriz.fonte(PAPEL_STATUS_DAY)
    fonte = matriz.tabela(PAPEL_STATUS_DAY)
    campo = (fonte_status.campo('afastamento') if fonte_status else None) or 'afastado'
    if registro is None:
        return Verificacao('sem_abono', None, MOTIVO_SEM_REGISTRO, fonte, campo)
    if campo not in registro:
        return Verificacao('sem_abono', None, 'Campo de afastamento não consultado.', fonte, campo)
    valor = _texto(registro.get(campo))
    if valor is None:
        return Verificacao('sem_abono', True, 'Sem atestado, afastamento ou justificativa no dia.',
                           fonte, campo, None)
    return Verificacao('sem_abono', False, MOTIVO_ABONO, fonte, campo, valor)


def classificar_ausencia(valor, abonaveis):
    """Separa justificativa abonavel de afastamento/atestado usando a lista oficial."""
    texto = _texto(valor)
    if texto is None:
        return dict(ausencia=None, justificativa=False, atestado=False)
    catalogo = {str(item).strip().casefold() for item in (abonaveis or ())}
    abonavel = texto.casefold() in catalogo
    return dict(ausencia=texto, justificativa=abonavel, atestado=not abonavel)


def _jornada_resolvida(registro, contexto, matriz):
    jornada = contexto.get('jornada') or {}
    if not jornada:
        return Verificacao('jornada_resolvida', None,
                           'Resolução de jornada não disponível nesta execução.',
                           matriz.tabela(PAPEL_COLABORADOR))
    origem = origem_da_jornada(jornada)
    if (origem == JORNADA_INDISPONIVEL or weekly_hours(jornada.get('jornada_semanal')) is None
            or jornada.get('status_resolucao') in ('CONFLITO', 'RESOLUCAO_INCOMPLETA')):
        return Verificacao('jornada_resolvida', None, MOTIVO_SEM_JORNADA,
                           matriz.tabela(PAPEL_COLABORADOR), 'jornada_semanal')
    return Verificacao('jornada_resolvida', True,
                       f'Jornada resolvida pela origem {origem}.',
                       jornada.get('fonte') or matriz.tabela(PAPEL_COLABORADOR),
                       jornada.get('campo') or 'jornada_semanal', jornada.get('jornada_semanal'))


def _houve_entrada(registro, contexto, matriz):
    fonte_status = matriz.fonte(PAPEL_STATUS_DAY)
    fonte = matriz.tabela(PAPEL_STATUS_DAY)
    campo = (fonte_status.campo('entrada') if fonte_status else None) or 'primeiro_checkin'
    if registro is None:
        return Verificacao('houve_entrada', None, MOTIVO_SEM_REGISTRO, fonte, campo)
    if campo not in registro:
        return Verificacao('houve_entrada', None, 'Campo de entrada não consultado.', fonte, campo)
    valor = registro.get(campo)
    entrou = not _vazio(valor)
    return Verificacao('houve_entrada', entrou,
                       'Entrada registrada na operação.' if entrou
                       else 'Sem entrada registrada: a saída não é cobrável.',
                       fonte, campo, _texto(valor))


CRITERIOS = {
    'colaborador_vigente': _colaborador_vigente,
    'dia_trabalhado': _dia_trabalhado,
    'sem_abono': _sem_abono,
    'jornada_resolvida': _jornada_resolvida,
    'houve_entrada': _houve_entrada,
}


def origem_da_jornada(jornada):
    """Rotula a origem da jornada na prioridade acordada.

    1 Involves (cadastro oficial, campo `nome_pai`) -> 2 RAW da operação ->
    3 configuração da operação -> 4 fallback padrão. E' rotulo de evidencia: nao muda a
    decisao de `shared.journey.resolve`, apenas explica de onde o numero veio.
    """
    if not jornada:
        return JORNADA_INDISPONIVEL
    rotulo = _texto(jornada.get('jornada_origem'))
    if rotulo and rotulo.upper() in (JORNADA_INVOLVES, JORNADA_RAW, JORNADA_CONFIGURACAO, JORNADA_FALLBACK):
        return rotulo.upper()
    if jornada.get('jornada_semanal') is None:
        return JORNADA_INDISPONIVEL
    fonte = (_texto(jornada.get('fonte')) or '').lower()
    if not fonte:
        return JORNADA_CONFIGURACAO
    return JORNADA_RAW if fonte.startswith('raw_') else JORNADA_INVOLVES


def _resultado(verificacoes):
    # Uma exceção comprovada invalida a cobrança mesmo com outra fonte incompleta.
    if any(item.atendido is False for item in verificacoes):
        return NAO_APLICAVEL
    if any(item.atendido is None for item in verificacoes):
        return INDISPONIVEL
    return CONFIRMADO if all(item.atendido for item in verificacoes) else NAO_APLICAVEL


def _motivo(verificacoes, resultado):
    if resultado == CONFIRMADO:
        return None
    if resultado == NAO_APLICAVEL:
        return next(item.descricao for item in verificacoes if item.atendido is False)
    pendente = next((item for item in verificacoes if item.atendido is None), None)
    if pendente is not None:
        return pendente.descricao
    reprovado = next((item for item in verificacoes if item.atendido is False), None)
    return reprovado.descricao if reprovado else None


def _indisponivel(achado, motivo, regra=None):
    return dict(
        regra=achado.get('tipo_problema'), colaborador=_texto(achado.get('colaborador')),
        data=_texto(achado.get('data_referencia')),
        fonte=achado.get('tabela_origem'), campo=(regra.campo if regra else None),
        esperado=(regra.valor_esperado if regra else None), encontrado=None,
        jornada_origem=JORNADA_INDISPONIVEL, justificativa=None, atestado=None,
        resultado=INDISPONIVEL, motivo=motivo, verificacoes=[])


def avaliar(achado, contexto, matriz, regras):
    """Comprovacao de um achado. Devolve sempre o mesmo contrato, nunca levanta excecao.

    `achado`   dict do detector (tipo_problema, colaborador, data_referencia, evidencia...)
    `contexto` o que ja foi lido das fontes: `status_day` (registro do dia), `jornada`
               (resolucao oficial) e `justificativas_abonaveis` (lista oficial)
    `matriz`   MatrizDeOrigem da marca
    `regras`   dict tipo_problema -> RegraDeEvidencia
    """
    if matriz is None:
        return _indisponivel(achado, MOTIVO_SEM_MATRIZ)
    regra = (regras or {}).get(achado.get('tipo_problema'))
    if regra is None:
        return _indisponivel(achado, MOTIVO_SEM_REGRA)
    if matriz.fonte(regra.papel) is None:
        return _indisponivel(achado, MOTIVO_SEM_FONTE, regra)

    registro = contexto.get('status_day') if isinstance(contexto, dict) else None
    contexto = contexto if isinstance(contexto, dict) else {}
    consultou_status = 'status_day' in contexto
    criterios = list(regra.criterios)
    if regra.tipo_problema in REGRAS_OPERACIONAIS:
        criterios = list(dict.fromkeys(criterios + list(CRITERIOS_OBRIGATORIOS)))
        if regra.tipo_problema == 'CHECKOUT_AUSENTE' and 'houve_entrada' not in criterios:
            criterios.append('houve_entrada')
    precisa_status = any(criterio in ('dia_trabalhado', 'sem_abono', 'houve_entrada')
                         for criterio in criterios)
    if precisa_status and not consultou_status:
        return _indisponivel(achado, MOTIVO_SEM_CONTEXTO, regra)

    verificacoes = []
    for nome in criterios:
        avaliador = CRITERIOS.get(nome)
        if avaliador is None:
            verificacoes.append(Verificacao(nome, None, 'Critério não implementado no motor.'))
            continue
        verificacoes.append(avaliador(registro, contexto, matriz))

    ocorrencia = None
    if regra.tipo_problema in REGRAS_OPERACIONAIS:
        ocorrencia = _comprovar_ocorrencia(achado, contexto, matriz, regra)
        verificacoes.append(ocorrencia)
    if not criterios:
        verificacoes.append(Verificacao('criterios', None, 'Regra sem critérios de validação.'))
    resultado = _resultado(verificacoes)
    jornada = contexto.get('jornada') or {}
    fonte_status = matriz.fonte(PAPEL_STATUS_DAY)
    campo_abono = (fonte_status.campo('afastamento') if fonte_status else None) or 'afastado'
    ausencia = classificar_ausencia(registro.get(campo_abono) if registro else None,
                                    contexto.get('justificativas_abonaveis'))
    evidencia = achado.get('evidencia') if isinstance(achado.get('evidencia'), dict) else {}

    return dict(
        regra=regra.tipo_problema,
        colaborador=_texto(achado.get('colaborador')),
        data=_texto(achado.get('data_referencia')),
        fonte=matriz.tabela(regra.papel),
        campo=regra.campo,
        esperado=regra.valor_esperado if regra.valor_esperado is not None else evidencia.get('valor_esperado'),
        encontrado=ocorrencia.valor if ocorrencia else _texto(evidencia.get('valor_encontrado')),
        jornada_origem=origem_da_jornada(jornada),
        # Ambos saem do mesmo campo de ausencia do status day; a lista oficial de
        # justificativas abonaveis e' o unico criterio que os separa.
        justificativa=ausencia['justificativa'],
        atestado=ausencia['atestado'],
        ausencia_registrada=ausencia['ausencia'],
        resultado=resultado,
        motivo=_motivo(verificacoes, resultado),
        verificacoes=[item.como_dicionario() for item in verificacoes],
    )


def _comprovar_ocorrencia(achado, contexto, matriz, regra):
    """Confere registros oficiais, sem aceitar o campo vazio declarado pelo detector."""
    fonte = matriz.tabela(regra.papel)
    campo = (matriz.fonte(regra.papel).campo('saida') or 'hora_saida'
             if regra.tipo_problema == 'INCONSISTENCIA_HORARIO' else regra.campo)
    def prova(atendido, motivo, valor=None):
        return Verificacao('ocorrencia_na_fonte', atendido, motivo, fonte, campo, valor)
    if not _texto(achado.get('colaborador')) or not _texto(achado.get('data_referencia')):
        return prova(None, 'Colaborador ou data do achado ausente.')
    registros = ([contexto.get('status_day')] if regra.papel == PAPEL_STATUS_DAY
                 else contexto.get('registros_origem'))
    if not registros or any(not isinstance(r, dict) for r in registros):
        return prova(None, 'Registro da ocorrência não consultado na fonte oficial.')
    fonte_config = matriz.fonte(regra.papel)
    nome = fonte_config.campo('colaborador') or 'colaborador'
    data = fonte_config.campo('data') or 'data_roteiro'
    if any(str(r.get(nome, '')).strip().casefold() != str(achado['colaborador']).strip().casefold()
           or str(r.get(data, ''))[:10] != str(achado['data_referencia'])[:10] for r in registros):
        return prova(None, 'Registro oficial não corresponde ao colaborador e à data.')
    if not campo or any(campo not in r for r in registros):
        return prova(None, 'Campo da ocorrência não consultado na fonte oficial.')
    if regra.tipo_problema == 'CHECKIN_ENTRADA_AUSENTE':
        ausente = all(_vazio(r[campo]) for r in registros)
        return prova(ausente, 'Entrada ausente na fonte oficial.' if ausente else 'Entrada já registrada.',
                     'vazio' if ausente else _texto(registros[0][campo]))
    if regra.tipo_problema == 'CHECKOUT_AUSENTE':
        entrada = fonte_config.campo('entrada') or 'hora_entrada'
        colunas = (entrada, 'checkout_sistema', 'checkout_registrado')
        if any(any(c not in r for c in colunas) for r in registros):
            return prova(None, 'Entrada ou saídas alternativas não consultadas.')
        ausente = any(not _vazio(r[entrada]) and all(_vazio(r[c]) for c in (campo,) + colunas[1:])
                      for r in registros)
        return prova(ausente, 'Checkout ausente após entrada registrada.' if ausente
                     else 'Nenhuma visita com entrada e checkout ausente.', 'vazio' if ausente else 'checkout presente ou sem entrada')
    # Mantém a regra validada: saída anterior à entrada; não inventa tolerância diária.
    from datetime import datetime, time
    entrada = fonte_config.campo('entrada') or 'hora_entrada'
    def segundos(v):
        texto = _texto(v)
        if not texto:
            raise ValueError('horário vazio')
        try:
            return datetime.fromisoformat(texto).timestamp()
        except ValueError:
            h = time.fromisoformat(texto)
            return h.hour * 3600 + h.minute * 60 + h.second
    evidencia = achado.get('evidencia') or {}
    pares = []
    for r in registros:
        if entrada not in r:
            return prova(None, 'Entrada não consultada na fonte oficial.')
        if evidencia.get('valor_inicio') is not None and (
                _texto(r[entrada]) != _texto(evidencia['valor_inicio']) or
                _texto(r[campo]) != _texto(evidencia.get('valor_fim'))):
            continue
        try:
            diferenca = segundos(r[campo]) - segundos(r[entrada])
        except (ValueError, TypeError, OverflowError):
            continue
        pares.append(diferenca)
        if diferenca < 0:
            return prova(True, 'Saída anterior à entrada registrada.',
                         f'entrada={r[entrada]}; saída={r[campo]}; diferença_segundos={diferenca:g}')
    return prova(False if pares else None, 'Horários consistentes.' if pares
                 else 'Par de horários oficial ausente, inválido ou divergente do achado.')


def deve_gerar_oportunidade(comprovacao):
    """Somente evidencia confirmada sustenta cobranca operacional."""
    return bool(comprovacao) and comprovacao.get('resultado') == CONFIRMADO
