"""Routing keywords, one frozen list per intent per language.

They live here rather than in `agent/agent.py` because the experiment's integrity
claim is about *these words*, not about the router: `eval/check_lexicon_freeze.py`
reads this module statically and refuses a re-freeze that loses a list, so the
claim that no keyword was tuned to the tickets it is scored on rests on a file
whose only content is keywords. The Spanish lists were authored before any Spanish
ticket existed (see `spanish-lexicon-proposal.md` in the implementation plan) —
that ordering is the claim, and moving them out of the router is what makes it
auditable.

`LEXICONS` is a dict literal of tuple literals of string constants, deliberately:
the freeze checker walks the AST and cannot see a lexicon that is computed at
import time. Anything cleverer here is invisible to the guard.

Matching is a raw substring test over `msg.lower()` — no tokenisation, no accent
folding. Spanish handles accents in the data instead, by truncating stems before
the accented vowel (`devoluc`, `direcci`, `lleg`) so one string matches both
spellings. Folding is not added because it would edit the matcher English also
runs through, and because naive NFD stripping maps `año` to `ano`.
"""
from __future__ import annotations

LEXICONS = {
    "en": {
        "_SAFETY": ("caught fire", "fire", "smoke", "smoking", "shock", "spark", "burn", "hazard", "dangerous", "explod"),
        "_PAYMENT": ("unauthorized", "dispute", "disputing", "chargeback", "charge back", "my bank"),
        "_FRAUD": ("fraud", "took over my account", "account takeover", "didn't make", "didn't place"),
        "_ADDRESS": ("change the delivery address", "change my address", "change the address", "reroute", "different address"),
        "_ABUSE": ("sue", "lawyer", "legal action", "reviews everywhere", "garbage", "trash"),
        "_RETURN": ("return", "send back", "send it back", "send this back", "refund", "money back", "exchange"),
        "_WISMO": ("where", "track", "tracking", "arrive", "arriving", "shipped", "ship", "delivery", "deliver"),
        "_DEFECTIVE": ("defective", "broken", "faulty", "doesn't work", "does not work", "not working",
                       "leak", "leaking", "cracked", "won't turn on", "dead", "malfunction"),
    },
    "es": {
        "_SAFETY": ("fuego", "incendi", "humo", "chisp", "quem",
                    "descarga eléctr", "descarga electr", "electrocut", "calambre",
                    "explot", "explos", "peligro"),
        "_PAYMENT": ("no autoric", "no autorizad", "disput", "contracargo", "mi banco", "al banco"),
        "_FRAUD": ("fraude", "suplant", "hacke", "robaron",
                   "no reconozco", "no hice el pedido", "no hice ese pedido", "no realic"),
        "_ADDRESS": ("cambiar la direcci", "cambiar mi direcci", "cambiar de direcci", "cambio de direcci",
                     "otra direcci", "nueva direcci",
                     "cambio de domicilio", "otro domicilio",
                     "redirig", "desviar"),
        "_ABUSE": ("demandar", "abogado", "acciones legales", "medidas legales", "denunci",
                   "reseñ", "resena", "redes sociales",
                   "basura", "porquer"),
        "_RETURN": ("devolv", "devoluc", "devu", "reembols",
                    "de vuelta", "mi dinero", "regresarl",
                    "cambiarl", "cambiar por", "cambio por", "cambio de talla", "cambiar de talla"),
        "_WISMO": ("dónde", "donde", "rastre", "seguimiento", "guía", "guia",
                   "env", "entreg", "lleg", "paquete"),
        "_DEFECTIVE": ("defectuos", "roto", "rota", "rotos", "rotas", "rompi", "dañad",
                       "descompuest", "quebrad", "agrietad",
                       "no funciona", "no sirve", "de funcionar", "no enciende", "no prende", "no anda",
                       "falla", "fallo", "falló", "mal funcionamiento",
                       "gotea", "goteo", "fuga"),
    },
}
