"""Executor de regras configuraveis: so executa o que esta cadastrado.

Separacao de responsabilidades
    CONFIGURACAO (tabelas `regra_*_configuracao`) define qual oportunidade existe, quando
    ela e analisada, quais condicoes a sustentam e quais excecoes a impedem.
    MOTOR (este modulo) apenas interpreta essa configuracao. Nenhum nome de regra, campo,
    limite ou excecao de negocio aparece aqui -- so o vocabulario tecnico (operadores,
    tipos de campo) que permite ao usuario montar uma regra sem escrever codigo.

Modulo puro
    Sem banco, sem pandas, sem rede. Recebe dicts e devolve dicts, entao a mesma logica
    serve a esteira (que cria a oportunidade) e a API (que decide o que a fila mostra) e
    pode ser testada sem infraestrutura.

Tres saidas possiveis para uma linha candidata
    confirmado     condicoes atendidas e nenhuma excecao aplicavel -> gera oportunidade;
    nao_aplicavel  alguma excecao configurada se aplica (atestado, afastamento...);
    indisponivel   faltou dado para decidir -- nunca vira oportunidade e nunca e' escondido.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
import re
import unicodedata

from shared.evidence_config import CONFIRMADO, INDISPONIVEL, NAO_APLICAVEL

STATUS_ATIVA = 'ATIVA'
STATUS_INATIVA = 'INATIVA'
STATUS_TRATAMENTO_ATIVO = 'ATIVO'
TRATAMENTO_CONFIRMADO = 'CONFIRMADO'

TIPO_CONDICAO = 'CONDICAO'
TIPO_EXCECAO = 'BLOQUEIO'

# Motivos pelos quais uma regra nao gera oportunidade. Sao codigos de evento, estaveis.
REGRA_NAO_CADASTRADA = 'REGRA_NAO_CADASTRADA'
REGRA_INATIVA = 'REGRA_INATIVA'
REGRA_SEM_GERACAO = 'REGRA_SEM_GERACAO'

# Sentinela: o registro que responderia a pergunta nao foi encontrado na fonte. E' diferente
# de "o registro existe e o campo esta vazio" -- o primeiro e' desconhecido, o segundo e' fato.
SEM_REGISTRO = object()


class ConfiguracaoInvalida(ValueError):
    """Regra cadastrada com operador, campo ou valor que o executor nao sabe interpretar."""


# --------------------------------------------------------------------------- vocabulario
OPERADORES = {
    'MAIOR_QUE': ('Maior que', 'maior que'),
    'MAIOR_IGUAL': ('Maior ou igual a', 'maior ou igual a'),
    'MENOR_QUE': ('Menor que', 'menor que'),
    'MENOR_IGUAL': ('Menor ou igual a', 'menor ou igual a'),
    'IGUAL_A': ('Igual a', 'igual a'),
    'DIFERENTE_DE': ('Diferente de', 'diferente de'),
    'IS NULL': ('Está vazio', 'está vazio'),
    'IS NOT NULL': ('Não está vazio', 'não está vazio'),
    'CONTEM': ('Contém', 'contém'),
    'EM_LISTA': ('Está na lista', 'está na lista'),
    'MENOR_QUE_CAMPO': ('Menor que o campo', 'menor que o campo'),
}
OPERADORES_SEM_VALOR = frozenset({'IS NULL', 'IS NOT NULL'})
OPERADORES_DE_ORDEM = frozenset({'MAIOR_QUE', 'MAIOR_IGUAL', 'MENOR_QUE', 'MENOR_IGUAL'})

TIPO_DURACAO = 'duracao'
TIPO_NUMERO = 'numero'
TIPO_PERCENTUAL = 'percentual'
TIPO_TEXTO = 'texto'
TIPO_BOOLEANO = 'booleano'
TIPO_HORA = 'hora'

# Campos que uma regra pode usar, por papel de fonte: rotulo de negocio e tipo. E' o
# "cardapio" da tela de configuracao -- nao decide nada, apenas diz o que existe.
CAMPOS = {
    'pdoh': {
        'horas_nao_registradas': ('Horas não registradas', TIPO_DURACAO),
        'ocio': ('Ócio', TIPO_DURACAO),
        'deslocamento': ('Deslocamento', TIPO_DURACAO),
        'produtividade': ('Produtividade', TIPO_DURACAO),
        'horas_programadas': ('Horas programadas', TIPO_DURACAO),
        'almoco': ('Almoço', TIPO_DURACAO),
        'percentual_produtividade': ('% de produtividade', TIPO_PERCENTUAL),
        'percentual_visitas': ('% de visitas', TIPO_PERCENTUAL),
        'percentual_pesquisas': ('% de pesquisas', TIPO_PERCENTUAL),
        'percentual_efetividade': ('% de efetividade', TIPO_PERCENTUAL),
        'primeiro_checkin': ('Primeiro check-in', TIPO_HORA),
        'ultimo_checkout': ('Último checkout', TIPO_HORA),
    },
    'colaborador': {
        'afastado': ('Afastamento ou atestado', TIPO_TEXTO),
        'tem_roteiro': ('Tem roteiro no dia', TIPO_BOOLEANO),
        'perfil': ('Perfil de acesso', TIPO_TEXTO),
        'ativo': ('Colaborador ativo', TIPO_BOOLEANO),
    },
    'checkin': {
        'hora_entrada': ('Hora de entrada', TIPO_HORA),
        'hora_saida': ('Hora de saída', TIPO_HORA),
    },
    'checkout': {
        'hora_saida': ('Hora de saída', TIPO_HORA),
    },
    'jornada': {
        'status_resolucao': ('Situação da jornada', TIPO_TEXTO),
        'jornada_semanal': ('Jornada semanal (horas)', TIPO_NUMERO),
    },
}


def rotulo_do_campo(papel, campo):
    """Nome de negocio do campo; sem cadastro, um rotulo legivel derivado do nome logico."""
    achado = CAMPOS.get(papel, {}).get(campo)
    if achado:
        return achado[0]
    texto = str(campo or '').replace('_', ' ').strip()
    return texto[:1].upper() + texto[1:]


def tipo_do_campo(papel, campo):
    achado = CAMPOS.get(papel, {}).get(campo)
    return achado[1] if achado else None


def rotulo_do_operador(operador):
    return OPERADORES.get(operador, (operador, operador))[0]


ROTULOS_PAPEL = {
    'pdoh': 'PDOH Platina',
    'colaborador': 'Cadastro de colaboradores',
    'checkin': 'Check-in',
    'checkout': 'Checkout',
    'jornada': 'Jornada',
    'visitas': 'Visitas',
    'pesquisas': 'Pesquisas',
}


def rotulo_do_papel(papel):
    return ROTULOS_PAPEL.get(papel) or str(papel or '').replace('_', ' ').capitalize()


# Operadores que a tela pode oferecer, por tipo de campo. `MENOR_QUE_CAMPO` compara dois campos
# e por isso nao e' editavel por valor; regras que o usam so' aceitam a chave ligar/desligar.
_ORDEM = ('MAIOR_QUE', 'MAIOR_IGUAL', 'MENOR_QUE', 'MENOR_IGUAL', 'IGUAL_A', 'DIFERENTE_DE',
          'IS NULL', 'IS NOT NULL')
OPERADORES_POR_TIPO = {
    TIPO_DURACAO: _ORDEM,
    TIPO_NUMERO: _ORDEM,
    TIPO_PERCENTUAL: _ORDEM,
    TIPO_HORA: _ORDEM,
    TIPO_TEXTO: ('IGUAL_A', 'DIFERENTE_DE', 'CONTEM', 'EM_LISTA', 'IS NULL', 'IS NOT NULL'),
    TIPO_BOOLEANO: ('IGUAL_A', 'DIFERENTE_DE'),
}


def operadores_do_tipo(tipo, atual=None):
    """[{codigo, rotulo}] que se pode escolher para um campo deste tipo."""
    codigos = OPERADORES_POR_TIPO.get(tipo, OPERADORES_POR_TIPO[TIPO_TEXTO])
    if atual and atual not in codigos:
        codigos = (atual,)                        # legado fora do cardapio: so' o que ja esta cadastrado
    return [dict(codigo=codigo, rotulo=rotulo_do_operador(codigo)) for codigo in codigos]


# --------------------------------------------------------------------------- coercao
def texto_normalizado(valor):
    """Comparacao de texto sem acento, caixa ou espaco duplicado."""
    if valor is None:
        return ''
    decomposto = unicodedata.normalize('NFKD', str(valor))
    sem_acento = ''.join(ch for ch in decomposto if not unicodedata.combining(ch))
    return ' '.join(sem_acento.casefold().split())


def vazio(valor):
    return valor is None or texto_normalizado(valor) in ('', 'nan', 'nat', 'none', 'null')


_DURACAO = re.compile(r'^\s*(-?)(\d{1,4}):([0-5]?\d)(?::([0-5]?\d))?\s*$')


def segundos(valor):
    """Duracao em segundos a partir de TIME/timedelta/'HH:MM[:SS]'. Outro formato: None."""
    if isinstance(valor, timedelta):
        return int(valor.total_seconds())
    if isinstance(valor, time):
        return valor.hour * 3600 + valor.minute * 60 + valor.second
    if isinstance(valor, str):
        achado = _DURACAO.match(valor)
        if achado:
            sinal, horas, minutos, seg = achado.groups()
            total = int(horas) * 3600 + int(minutos) * 60 + int(seg or 0)
            return -total if sinal else total
    return None


def numero(valor):
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float, Decimal)):
        return float(valor)
    if isinstance(valor, str):
        try:
            return float(valor.strip().replace(',', '.'))
        except ValueError:
            return None
    return None


def booleano(valor):
    if isinstance(valor, bool):
        return valor
    texto = texto_normalizado(valor)
    if texto in ('sim', 's', 'true', '1', 'verdadeiro', 'yes'):
        return True
    if texto in ('nao', 'n', 'false', '0', 'falso', 'no'):
        return False
    return None


def instante(valor):
    """datetime/time/ISO em algo comparavel. Tipos misturados nao se comparam."""
    if isinstance(valor, datetime):
        return valor
    if isinstance(valor, time):
        return valor
    if isinstance(valor, date):
        return datetime.combine(valor, time.min)
    if isinstance(valor, str) and valor.strip():
        texto = valor.strip()
        for formato in (datetime.fromisoformat, time.fromisoformat):
            try:
                return formato(texto)
            except ValueError:
                continue
    return None


def _par_ordenavel(atual, esperado, tipo):
    """Par (a, b) na mesma escala, ou None quando nao ha como comparar com seguranca."""
    if tipo == TIPO_DURACAO or (segundos(atual) is not None and segundos(esperado) is not None):
        a, b = segundos(atual), segundos(esperado)
        return (a, b) if a is not None and b is not None else None
    if tipo in (TIPO_NUMERO, TIPO_PERCENTUAL) or (numero(atual) is not None and numero(esperado) is not None):
        a, b = numero(atual), numero(esperado)
        return (a, b) if a is not None and b is not None else None
    a, b = instante(atual), instante(esperado)
    if a is not None and b is not None and type(a) is type(b):
        return a, b
    return None


def _iguais(atual, esperado, tipo):
    if tipo == TIPO_BOOLEANO or isinstance(esperado, bool) or booleano(esperado) is not None:
        a, b = booleano(atual), booleano(esperado)
        if a is not None and b is not None:
            return a == b
    a, b = segundos(atual), segundos(esperado)
    if a is not None and b is not None:
        return a == b
    a, b = numero(atual), numero(esperado)
    if a is not None and b is not None and tipo != TIPO_TEXTO:
        return a == b
    return texto_normalizado(atual) == texto_normalizado(esperado)


def comparar(operador, atual, esperado, tipo=None, outro=None):
    """Aplica UM operador. True/False sao fatos; None significa "sem como decidir".

    Ordem (`>`, `<`...) contra valor ausente e' desconhecido, nao falso: a ausencia nao
    prova que o valor e' pequeno. Ja `CONTEM`/`EM_LISTA` sobre campo vazio e' falso -- o
    registro existe e simplesmente nao traz aquele texto.
    """
    if operador not in OPERADORES:
        raise ConfiguracaoInvalida(f'Operador desconhecido: {operador!r}')
    if operador == 'IS NULL':
        return vazio(atual)
    if operador == 'IS NOT NULL':
        return not vazio(atual)
    if operador == 'MENOR_QUE_CAMPO':
        a, b = instante(atual), instante(outro)
        if a is None or b is None or type(a) is not type(b):
            return None
        return a < b
    if operador in OPERADORES_DE_ORDEM:
        if vazio(atual):
            return None
        par = _par_ordenavel(atual, esperado, tipo)
        if par is None:
            return None
        a, b = par
        return {'MAIOR_QUE': a > b, 'MAIOR_IGUAL': a >= b,
                'MENOR_QUE': a < b, 'MENOR_IGUAL': a <= b}[operador]
    if operador in ('IGUAL_A', 'DIFERENTE_DE'):
        igual = _iguais(atual, esperado, tipo)
        return igual if operador == 'IGUAL_A' else not igual
    if vazio(atual):
        return False
    if operador == 'CONTEM':
        return texto_normalizado(esperado) in texto_normalizado(atual)
    lista = esperado if isinstance(esperado, (list, tuple, set)) else [esperado]
    return texto_normalizado(atual) in {texto_normalizado(item) for item in lista}


# --------------------------------------------------------------------------- descricao
def _formatar_valor(valor):
    if isinstance(valor, bool):
        return 'Sim' if valor else 'Não'
    if isinstance(valor, timedelta):                 # coluna TIME: 0:30:00 -> 00:30:00
        total = int(valor.total_seconds())
        return f'{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}'
    if isinstance(valor, (list, tuple, set)):
        return ', '.join(str(item) for item in valor)
    if isinstance(valor, dict):
        return ', '.join(str(item) for item in valor.values())
    return '' if valor is None else str(valor)


def descrever_condicao(condicao):
    """"Horas não registradas maior que 00:00": a condicao como o lider a leria."""
    campo = rotulo_do_campo(condicao.get('papel_fonte'), condicao.get('campo_logico'))
    operador = condicao.get('operador')
    texto = OPERADORES.get(operador, (operador, operador))[1]
    if operador in OPERADORES_SEM_VALOR:
        return f'{campo} {texto}'
    valor = condicao.get('valor_esperado')
    if operador == 'MENOR_QUE_CAMPO' and isinstance(valor, dict):
        valor = rotulo_do_campo(condicao.get('papel_fonte'), valor.get('campo'))
    return f'{campo} {texto} {_formatar_valor(valor)}'.strip()


def validar_valor(operador, tipo, valor):
    """Valor de uma condicao editada na tela, ja no formato em que a regra o guarda.

    Levanta `ConfiguracaoInvalida` com a mensagem que o usuario le. O que passa aqui e' o que
    `comparar` sabe interpretar: nada e' gravado para ser descoberto invalido na esteira.
    """
    if operador in OPERADORES_SEM_VALOR:
        return None
    if operador == 'EM_LISTA':
        itens = valor if isinstance(valor, (list, tuple, set)) else str(valor or '').split(',')
        limpos = [str(item).strip() for item in itens if str(item).strip()]
        if not limpos:
            raise ConfiguracaoInvalida('Informe ao menos um valor para a lista.')
        return limpos
    if tipo == TIPO_DURACAO:
        total = segundos(valor) if isinstance(valor, str) else None
        if total is None or total < 0:
            raise ConfiguracaoInvalida('Informe a duração no formato HH:MM (por exemplo, 00:30).')
        horas, resto = divmod(total, 3600)
        minutos, seg = divmod(resto, 60)
        return f'{horas:02d}:{minutos:02d}' + (f':{seg:02d}' if seg else '')
    if tipo in (TIPO_NUMERO, TIPO_PERCENTUAL):
        convertido = numero(valor)
        if convertido is None:
            raise ConfiguracaoInvalida('Informe um número válido.')
        return int(convertido) if convertido == int(convertido) else convertido
    if tipo == TIPO_BOOLEANO:
        convertido = booleano(valor)
        if convertido is None:
            raise ConfiguracaoInvalida('Informe Sim ou Não.')
        return convertido
    if tipo == TIPO_HORA:
        if not isinstance(valor, str) or instante(valor) is None:
            raise ConfiguracaoInvalida('Informe um horário válido (por exemplo, 18:00).')
        return valor.strip()
    texto = str(valor if valor is not None else '').strip()
    if not texto:
        raise ConfiguracaoInvalida('Informe o valor da condição.')
    return texto


# --------------------------------------------------------------------------- porta de decisao
def gera_oportunidade(regra, tratamentos):
    """A regra pode criar oportunidade? Devolve (liberado, motivo_se_nao).

    Uma unica definicao para a esteira (que cria) e para a API (que exibe): nenhum dos dois
    decide sozinho o que "regra ativa" significa.
        cadastrada   existe linha em `regra_configuracao` para marca/operacao/codigo;
        ativa        status ATIVA e geracao automatica ligada;
        gera         a tratativa do resultado CONFIRMADO tem `gera_oportunidade` ligado.
    """
    if not regra:
        return False, REGRA_NAO_CADASTRADA
    if regra.get('status') != STATUS_ATIVA or not regra.get('geracao_automatica_ativa'):
        return False, REGRA_INATIVA
    confirmado = next((t for t in (tratamentos or ())
                       if t.get('resultado') == TRATAMENTO_CONFIRMADO
                       and t.get('status', STATUS_TRATAMENTO_ATIVO) == STATUS_TRATAMENTO_ATIVO), None)
    if not confirmado or not confirmado.get('gera_oportunidade'):
        return False, REGRA_SEM_GERACAO
    return True, None


def codigos_liberados(regras, tratamentos):
    """{(marca, operacao): {codigos}} das regras que podem gerar oportunidade agora.

    `regras`: linhas de regra_configuracao; `tratamentos`: linhas de regra_tratamento_configuracao.
    """
    por_regra = {}
    for tratamento in tratamentos or ():
        por_regra.setdefault(tratamento['configuracao_id'], []).append(tratamento)
    liberados = {}
    for regra in regras or ():
        ok, _ = gera_oportunidade(regra, por_regra.get(regra['configuracao_id'], []))
        if ok:
            liberados.setdefault((regra['marca'], regra['operacao']), set()).add(regra['codigo_interno'])
    return liberados


# --------------------------------------------------------------------------- avaliacao
def _valor_da_condicao(condicao, linha):
    tipo = tipo_do_campo(condicao.get('papel_fonte'), condicao.get('campo_logico'))
    esperado = condicao.get('valor_esperado')
    outro = None
    if condicao.get('operador') == 'MENOR_QUE_CAMPO':
        campo_referencia = esperado.get('campo') if isinstance(esperado, dict) else esperado
        outro = linha.get(campo_referencia)
    return tipo, esperado, outro


def avaliar_condicao(condicao, linha):
    """Avalia uma condicao sobre a linha da fonte primaria (campo logico -> valor)."""
    tipo, esperado, outro = _valor_da_condicao(condicao, linha)
    return comparar(condicao['operador'], linha.get(condicao['campo_logico']), esperado, tipo, outro)


def _resumo_configuracao(regra, condicoes, excecoes):
    return {
        'tempo_minimo_minutos': int(regra.get('tempo_minimo_minutos') or 0),
        'condicoes': [dict(campo=c['campo_logico'], campo_rotulo=rotulo_do_campo(c['papel_fonte'], c['campo_logico']),
                           operador=c['operador'], operador_rotulo=rotulo_do_operador(c['operador']),
                           valor=c.get('valor_esperado'), descricao=descrever_condicao(c))
                      for c in condicoes],
        'excecoes': [dict(ordem=e.get('ordem'), nome=e.get('descricao'), campo=e['campo_logico'],
                          operador=e['operador'], valor=e.get('valor_esperado'),
                          ativa=e.get('status') == STATUS_ATIVA) for e in excecoes],
    }


def avaliar_regra(regra, linha, provedor, *, colaborador, data, fonte_rotulo=None, fonte_tabela=None):
    """Decide o que fazer com UMA linha da fonte primaria.

    Devolve None quando a linha nao e' candidata (condicao nao atendida ou abaixo do tempo
    minimo): nao ha o que registrar. Caso contrario, a comprovacao completa -- inclusive a
    configuracao que foi usada, para que a oportunidade se explique sozinha depois.

    `provedor(excecao, colaborador, data)` devolve o valor que a excecao precisa examinar ou
    `SEM_REGISTRO` quando a fonte nao tem o registro daquele colaborador nesse dia.
    """
    todas = regra.get('condicoes') or []
    condicoes = [c for c in todas if c.get('tipo', TIPO_CONDICAO) == TIPO_CONDICAO
                 and c.get('status', STATUS_ATIVA) == STATUS_ATIVA]
    excecoes = [c for c in (regra.get('excecoes') or [])
                if c.get('status', STATUS_ATIVA) == STATUS_ATIVA]
    if not condicoes:
        raise ConfiguracaoInvalida(f"Regra {regra.get('codigo_interno')} sem condicao ativa.")

    verificacoes, desconhecidas = [], []
    primaria = condicoes[0]
    encontrado = linha.get(primaria['campo_logico'])
    for condicao in condicoes:
        atendida = avaliar_condicao(condicao, linha)
        if atendida is False:
            return None
        verificacoes.append(dict(
            criterio='condicao', rotulo='Condição da regra', atendido=atendida,
            descricao=descrever_condicao(condicao), fonte=fonte_tabela, campo=condicao['campo_logico'],
            valor=_formatar_valor(linha.get(condicao['campo_logico'])) or None))
        if atendida is None:
            desconhecidas.append(f"{rotulo_do_campo(condicao['papel_fonte'], condicao['campo_logico'])} sem valor na fonte oficial")

    tempo_minimo = int(regra.get('tempo_minimo_minutos') or 0)
    if tempo_minimo and not desconhecidas:
        medido = segundos(encontrado)
        if medido is None:
            desconhecidas.append('Tempo medido não interpretável para o tempo mínimo')
        elif medido < tempo_minimo * 60:
            return None
        verificacoes.append(dict(
            criterio='tempo_minimo', rotulo='Tempo mínimo', atendido=medido is not None,
            descricao=f'Tempo mínimo de {tempo_minimo} minuto(s)', fonte=fonte_tabela,
            campo=primaria['campo_logico'], valor=_formatar_valor(encontrado) or None))

    aplicadas, sem_dado = [], []
    for excecao in excecoes:
        valor = provedor(excecao, colaborador, data)
        if valor is SEM_REGISTRO:
            aplica, mostrado = None, None
            sem_dado.append(excecao.get('descricao'))
        else:
            tipo = tipo_do_campo(excecao.get('papel_fonte'), excecao.get('campo_logico'))
            aplica = comparar(excecao['operador'], valor, excecao.get('valor_esperado'), tipo)
            mostrado = _formatar_valor(valor) or None
            if aplica:
                aplicadas.append((excecao.get('descricao'), mostrado))
            elif aplica is None:
                sem_dado.append(excecao.get('descricao'))
        nome = excecao.get('descricao') or rotulo_do_campo(excecao.get('papel_fonte'), excecao['campo_logico'])
        if aplica is None:
            descricao = f'{nome}: registro não localizado na fonte oficial'
        elif aplica:
            descricao = f'{nome}: aplicada' + (f' ({mostrado})' if mostrado else '')
        else:
            descricao = f'{nome}: não se aplica ao dia'
        verificacoes.append(dict(
            criterio='excecao', rotulo=f'Exceção: {nome}',
            # True = a excecao nao barra; False = barra; None = nao foi possivel verificar.
            atendido=None if aplica is None else not aplica,
            descricao=descricao, fonte=None, campo=excecao['campo_logico'], valor=mostrado))

    if aplicadas:
        resultado = NAO_APLICAVEL
        nome, detalhe = aplicadas[0]
        motivo = f'Exceção aplicada: {nome}' + (f' ({detalhe})' if detalhe else '')
        resumo = f'Não gera oportunidade: {motivo.lower()}'
    elif desconhecidas or sem_dado:
        resultado = INDISPONIVEL
        motivo = ('; '.join(desconhecidas) if desconhecidas
                  else 'Sem dado para verificar: ' + ', '.join(str(n) for n in sem_dado))
        resumo = 'Dados insuficientes; nenhuma oportunidade foi criada'
    else:
        resultado, motivo, resumo = CONFIRMADO, None, 'Oportunidade gerada'

    rotulo_jornada = getattr(provedor, 'jornada_origem', None)
    horas_jornada = getattr(provedor, 'jornada_semanal', None)
    return dict(
        regra=regra.get('codigo_interno'), colaborador=colaborador, data=str(data)[:10] if data else None,
        fonte=fonte_rotulo or fonte_tabela, fonte_tabela=fonte_tabela, campo=primaria['campo_logico'],
        esperado=descrever_condicao(primaria), encontrado=_formatar_valor(encontrado) or None,
        jornada_origem=(rotulo_jornada(colaborador, data) if callable(rotulo_jornada) else None) or 'INDISPONIVEL',
        # Jornada semanal resolvida para o dia (evidencia; nao altera a decisao da regra).
        jornada_semanal=horas_jornada(colaborador, data) if callable(horas_jornada) else None,
        justificativa=None, atestado=None,
        resultado=resultado, motivo=motivo, resultado_regra=resumo,
        # Registra TODAS as excecoes, inclusive as desligadas: para explicar por que um dia de
        # atestado gerou oportunidade e' preciso mostrar que 'Atestado' estava desligado.
        configuracao_utilizada=_resumo_configuracao(regra, condicoes, regra.get('excecoes') or []),
        verificacoes=verificacoes)
