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

Entries are read as prefixes: `agent._has` requires a leading word boundary and no
trailing one, so a stem still matches the longer word (`devoluc` → *devolución*)
but cannot start mid-word (`roto` no longer fires inside *prototipo*, and no token
ending `-no` completes `no funciona`). Write entries accordingly — a stem must be a
real word-start, and a suffix-only fragment will never match.

There is still no tokenisation and no accent folding. Spanish handles accents in
the data, by truncating stems before the accented vowel (`devoluc`, `direcci`,
`lleg`) so one string matches both spellings. Folding is not added because it would
edit the matcher English also runs through, and because naive NFD stripping maps
`año` to `ano`. Indonesian needs no accent folding; stems are written in standard
Latin orthography. Known collisions (frozen with the lists, not bugs to patch):
`retur` matches English *return* (code-switch, intended); `mati` is a broad
defective stem.
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
    # Indonesian (T14): authored from the English/Spanish *categories*, before any
    # ID-* ticket existed. Freeze immediately; do not add words after seeing tickets.
    "id": {
        "_SAFETY": ("kebakaran", "terbakar", "kebakar", "asap", "percik",
                    "tersengat", "kejutan listrik", "kesetrum", "setrum", "nyetrum",
                    "meledak", "ledakan", "bahaya", "berbahaya", "hangus"),
        "_PAYMENT": ("tidak sah", "tak sah", "tidak diotorisasi", "tanpa izin",
                     "sengketa", "chargeback", "bank saya", "ke bank"),
        "_FRAUD": ("penipuan", "penipu", "diretas", "akun diambil",
                   "bukan saya yang pesan", "tidak memesan", "tidak pesan",
                   "bukan pesanan saya"),
        "_ADDRESS": ("ubah alamat", "ganti alamat", "ganti alamat pengiriman",
                     "alamat lain", "alamat berbeda", "alamat baru", "alamat kantor"),
        "_ABUSE": ("gugat", "pengacara", "tindakan hukum", "proses hukum",
                   "review di mana-mana", "review dimana-mana", "sampah", "ancam"),
        "_RETURN": ("pengembalian", "kembalikan", "mengembalikan", "retur",
                    "refund", "uang kembali", "tukar", "penukaran"),
        "_WISMO": ("dimana", "di mana", "lacak", "pelacak", "tracking", "resi",
                   "pengirim", "dikirim", "mengirim", "ngirim", "paket"),
        "_DEFECTIVE": ("rusak", "cacat", "pecah", "retak", "bocor",
                       "tidak berfungsi", "tidak nyala", "tidak menyala",
                       "ga nyala", "gak nyala", "mati", "bermasalah",
                       "tidak bisa dipakai"),
    },
}
