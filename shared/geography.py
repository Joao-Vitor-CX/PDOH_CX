"""Accepted Brazilian state labels and abbreviations (without changing source values)."""
import unicodedata


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value if value is not None else '').strip().upper())
                   if not unicodedata.combining(c))


STATES = dict(zip(
    'AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO'.split(),
    ['Acre','Alagoas','Amapa','Amazonas','Bahia','Ceara','Distrito Federal','Espirito Santo',
     'Goias','Maranhao','Mato Grosso','Mato Grosso do Sul','Minas Gerais','Para','Paraiba','Parana',
     'Pernambuco','Piaui','Rio de Janeiro','Rio Grande do Norte','Rio Grande do Sul','Rondonia',
     'Roraima','Santa Catarina','Sao Paulo','Sergipe','Tocantins']))
VALID = set(STATES) | {normalized(v) for v in STATES.values()}


def valid_state(value):
    return normalized(value) in VALID
