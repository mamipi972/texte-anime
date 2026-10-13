#!/usr/bin/env python3
# Texte animé — greffon pour GIMP 3
# Copyright (C) 2026 mamipi972
# SPDX-License-Identifier: GPL-3.0-or-later
# Greffon GIMP 3.2 : moteur d'animation de texte.
#
#   Jusqu'à 3 écrans enchaînés, chacun avec son texte et son effet
#   × unité (lettre / mot / ligne / bloc) × courbe d'accélération × ordre et décalage
#   → export WebP / GIF (natifs GIMP) ou MP4 (ffmpeg, avec sons de synthèse optionnels).
#
# Installation : copier le dossier "texte-anime" (avec le sous-dossier "apercus")
# dans %APPDATA%\GIMP\3.2\plug-ins\ puis relancer GIMP.
# Menu : Fichier > Créer > Animation > Texte animé…
# Interface en français si GIMP est en français, sinon en anglais.

import array
import glob
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import wave

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gegl, GObject, GLib, Gio

PROC_NAME = "python-fu-texte-anime"
N_SCREENS = 3
HERE = os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------------------ langue
def _is_french():
    for name in [os.environ.get("LANGUAGE", ""), os.environ.get("LANG", "")] + \
            list(GLib.get_language_names()):
        name = (name or "").lower()
        if name and name not in ("c", "posix"):
            return name.startswith("fr")
    return False


FR = _is_french()


def T(fr, en):
    return fr if FR else en


# ------------------------------------------------------------------ choix
EFFECTS = {
    "fondu":   (T("Fondu", "Fade"), T("Les éléments apparaissent en fondu en remontant.",
                                         "Elements fade in while rising.")),
    "machine": (T("Machine à écrire", "Typewriter"),
                T("Le texte se tape lettre par lettre, avec curseur.",
                  "Text is typed letter by letter, with a cursor.")),
    "chute":   (T("Chute", "Drop"), T("Les éléments tombent d'en haut et rebondissent.",
                                       "Elements drop from above and bounce.")),
    "alterne": (T("Alterné", "Alternate"),
                T("Un élément sur deux arrive par le haut, l'autre par le bas.",
                  "Every other element comes from the top, the rest from the bottom.")),
    "glisser": (T("Glisser", "Slide up"),
                T("Le texte monte depuis une fente invisible.",
                  "Text slides up from an invisible slit.")),
    "rideau":  (T("Rideau", "Wipe"),
                T("Un volet de couleur balaie puis dévoile le texte.",
                  "A colored panel sweeps across and reveals the text.")),
    "stomp":   (T("Stomp", "Stomp"),
                T("Les éléments arrivent en grand et s'écrasent à leur taille.",
                  "Elements land from a large scale with a punch.")),
    "flou":    (T("Fondu flou", "Blur in"),
                T("Les lettres passent du flou au net en se resserrant.",
                  "Letters go from blurred to sharp while tightening.")),
    "generique": (T("Générique", "Credits"),
                  T("Le texte défile de bas en haut, comme un générique de film.",
                    "Text scrolls from bottom to top, like movie credits.")),
    "bandeau": (T("Bandeau", "Ticker"),
                T("Le texte défile sur une seule ligne, de droite à gauche.",
                  "Text scrolls on a single line, right to left.")),
    "neon":    (T("Néon", "Neon"),
                T("Le texte s'allume en grésillant, avec un halo de la couleur d'accent.",
                  "Text flickers on with a glow in the accent color.")),
    "remplissage": (T("Remplissage", "Fill"),
                    T("Le contour des lettres apparaît, puis la couleur monte à l'intérieur.",
                      "Letter outlines appear, then color rises inside them.")),
    "focus":   (T("Mise au point", "Focus"),
                T("Un cadre passe de mot en mot : le mot visé est net, le reste flou.",
                  "A frame moves from word to word: that word is sharp, the rest blurred.")),
    "vitesse": (T("Traînée", "Speed"),
                T("Les éléments arrivent très vite de la gauche avec un flou de mouvement.",
                  "Elements rush in from the left with motion blur.")),
    "parallaxe": (T("Parallaxe", "Parallax"),
                  T("Les lignes glissent à des vitesses différentes devant un grand texte "
                    "fantôme, comme en profondeur.",
                    "Lines slide at different speeds over a large ghost text, "
                    "giving depth.")),
    "detourage": (T("Tracé", "Draw-on"),
                  T("Le contour des lettres se dessine trait par trait, puis l'intérieur "
                    "se remplit.",
                    "Letter outlines are drawn stroke by stroke, then filled in.")),
    "liquide": (T("Liquide", "Liquid"),
                T("Les lettres naissent de gouttes qui fusionnent. Deux écrans Liquide à "
                  "la suite : le premier texte se transforme en le second (morphing).",
                  "Letters grow from merging drops. Two Liquid screens in a row: the first "
                  "text morphs into the second.")),
    "eclats":  (T("Éclats", "Shatter"),
                T("Le texte se reconstitue à partir d'éclats ; à la sortie, il vole en "
                  "morceaux. Effet plus lent à créer.",
                  "Text assembles from shards; on exit it shatters. Slower to render.")),
}
SCROLL_EFFECTS = ("generique", "bandeau")  # défilement continu : ni maintien ni sortie
# Galerie : 3 onglets d'une seule rangée (la fenêtre ne grandit pas avec les effets).
GALLERY_TABS = (
    (T("Apparition", "Reveal"), ["fondu", "flou", "machine", "rideau", "remplissage"]),
    (T("Mouvement", "Motion"), ["chute", "alterne", "glisser", "stomp", "vitesse"]),
    (T("Ambiance", "Mood"), ["neon", "focus", "parallaxe", "generique", "bandeau"]),
    (T("Spéciaux", "Special"), ["detourage", "liquide", "eclats"]),
)
GALLERY_PER_ROW = 5
UNITS = {"auto": T("Auto (selon l'effet)", "Auto (per effect)"), "lettre": T("Lettre", "Letter"),
         "mot": T("Mot", "Word"), "ligne": T("Ligne", "Line"),
         "bloc": T("Bloc entier", "Whole block")}
EASINGS = {"auto": T("Auto (selon l'effet)", "Auto (per effect)"),
           "lineaire": T("Linéaire", "Linear"), "douce": T("Douce", "Smooth"),
           "rebond": T("Dépassement", "Overshoot"), "elastique": T("Élastique", "Elastic"),
           "ricochet": T("Ricochet (balle)", "Bounce")}
ORDERS = {"normal": T("Normal", "Normal"), "inverse": T("Inverse", "Reverse"),
          "centre": T("Depuis le centre", "From center"),
          "aleatoire": T("Aléatoire", "Random")}
FORMATS = {"mp4": T("Vidéo MP4", "MP4 video"), "webp": T("WebP animé", "Animated WebP"),
           "gif": T("GIF animé", "Animated GIF")}
SIZE_PRESETS = {
    "carre":    (1080, 1080, T("Carré 1:1 — 1080×1080", "Square 1:1 — 1080×1080")),
    "paysage":  (1920, 1080, T("Paysage 16:9 — 1920×1080", "Landscape 16:9 — 1920×1080")),
    "portrait": (1080, 1920, T("Portrait 9:16 — 1080×1920", "Portrait 9:16 — 1080×1920")),
    "quatre5":  (1080, 1350, T("Vertical 4:5 — 1080×1350", "Vertical 4:5 — 1080×1350")),
    "hd":       (1280, 720, T("Paysage 16:9 — 1280×720", "Landscape 16:9 — 1280×720")),
    "perso":    (0, 0, T("Personnalisée", "Custom")),
}

# Réglages « auto » par effet : unité animée et courbe.
EFFECT_DEFAULTS = {
    "fondu":   ("lettre", "douce"),
    "machine": ("lettre", "lineaire"),
    "chute":   ("lettre", "ricochet"),
    "alterne": ("lettre", "rebond"),
    "glisser": ("ligne", "douce"),
    "rideau":  ("ligne", "douce"),
    "stomp":   ("mot", "rebond"),
    "flou":    ("lettre", "douce"),
    "generique": ("ligne", "lineaire"),
    "bandeau": ("bloc", "lineaire"),
    "neon":    ("mot", "lineaire"),
    "remplissage": ("mot", "douce"),
    "focus":   ("mot", "douce"),
    "vitesse": ("mot", "rebond"),
    "parallaxe": ("ligne", "douce"),
    "detourage": ("mot", "douce"),
    "liquide": ("bloc", "douce"),
    "eclats":  ("ligne", "douce"),
}


# ------------------------------------------------------------------ courbes
def ease_douce(p):
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def ease_rebond(p, s=1.70158):
    return 1 + (s + 1) * (p - 1) ** 3 + s * (p - 1) ** 2


def ease_elastique(p):
    if p in (0.0, 1.0):
        return p
    return 2 ** (-10 * p) * math.sin((p * 10 - 0.75) * (2 * math.pi / 3)) + 1


def ease_ricochet(p):
    n, d = 7.5625, 2.75
    if p < 1 / d:
        return n * p * p
    if p < 2 / d:
        p -= 1.5 / d
        return n * p * p + 0.75
    if p < 2.5 / d:
        p -= 2.25 / d
        return n * p * p + 0.9375
    p -= 2.625 / d
    return n * p * p + 0.984375


EASE_FUNCS = {"lineaire": lambda p: p, "douce": ease_douce, "rebond": ease_rebond,
              "elastique": ease_elastique, "ricochet": ease_ricochet}


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


# ------------------------------------------------------------------ outils
def hex_color(value):
    # Nécessite Gegl.init() (fait dans do_create_procedure), sinon noir transparent.
    return Gegl.Color.new(value)


def default_font():
    """Police du contexte ; au démarrage (mode console) GIMP peut encore charger les polices."""
    for attempt in range(2):
        font = Gimp.context_get_font() or Gimp.Font.get_by_name("Sans-serif")
        if font is not None:
            return font
        Gimp.fonts_refresh()  # attend la fin du chargement des polices
    return None


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    pattern = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet",
                           "Packages", "*FFmpeg*", "*", "bin", "ffmpeg.exe")
    hits = glob.glob(pattern)
    return hits[0] if hits else None


def run_export_proc(name, image, path, **props):
    proc = Gimp.get_pdb().lookup_procedure(name)
    config = proc.create_config()
    config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    config.set_property("image", image)
    config.set_property("file", Gio.File.new_for_path(path))
    for key, value in props.items():
        config.set_property(key.replace("_", "-"), value)
    return proc.run(config).index(0) == Gimp.PDBStatusType.SUCCESS


def folder_path(value):
    """Texte du paramètre « folder » -> dossier existant (Images par défaut).
    Accepte aussi l'ancien format « file:///C:\\... » des réglages enregistrés."""
    value = (value or "").strip().strip('"')
    if value.lower().startswith("file:"):
        value = urllib.parse.unquote(value[5:].lstrip("/\\"))
    if value and os.path.isdir(value):
        return os.path.normpath(value)
    return os.path.join(os.path.expanduser("~"), "Pictures")


def resolve_output(folder, name, fmt):
    """Dossier (Images par défaut) + nom ; l'extension est toujours celle du format."""
    base = folder_path(folder)
    name = os.path.basename(name.strip().strip('"')) or "texte-anime"
    root, ext = os.path.splitext(name)
    if ext.lower() in (".webp", ".gif", ".mp4"):
        name = root
    return os.path.normpath(os.path.join(base, name + "." + fmt))


def unique_path(path):
    """intro.mp4 -> intro-2.mp4, intro-3.mp4… (premier nom libre)."""
    root, ext = os.path.splitext(path)
    n = 2
    while os.path.exists("%s-%d%s" % (root, n, ext)):
        n += 1
    return "%s-%d%s" % (root, n, ext)


def confirm_overwrite(path):
    """Fichier existant : renvoie le chemin à utiliser, ou None si l'utilisateur annule."""
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    dlg = Gtk.MessageDialog(message_type=Gtk.MessageType.QUESTION,
                            buttons=Gtk.ButtonsType.NONE,
                            text=T("Le fichier « %s » existe déjà.",
                                   "The file “%s” already exists.") % os.path.basename(path))
    dlg.format_secondary_text(T("Voulez-vous le remplacer ou garder les deux fichiers ?\n"
                                "« Garder les deux » enregistrera « %s ».",
                                "Replace it, or keep both files?\n"
                                "“Keep both” will save “%s”.")
                              % os.path.basename(unique_path(path)))
    dlg.add_buttons(T("Annuler", "Cancel"), Gtk.ResponseType.CANCEL,
                    T("Garder les deux", "Keep both"), 2,
                    T("Remplacer", "Replace"), 1)
    dlg.set_default_response(2)
    answer = dlg.run()
    dlg.destroy()
    if answer == 1:
        return path
    if answer == 2:
        return unique_path(path)
    return None


def clip_rect(x, y, w, h, width, height):
    """Rectangle limité à l'image, ou None s'il est entièrement dehors.
    Indispensable : dans GIMP, remplir avec une sélection vide remplit TOUT le calque."""
    x0, y0 = max(0, round(x)), max(0, round(y))
    x1, y1 = min(width, round(x + w)), min(height, round(y + h))
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    return x0, y0, x1 - x0, y1 - y0


# ------------------------------------------------------------------ mise en page
def fit_layout(text, font, size, width, height, allow_tall=False):
    """Coupe les lignes trop longues (retour à la ligne automatique) et réduit la taille
    du texte si le bloc dépasse encore la marge de sécurité (88 % de l'image).
    allow_tall : le bloc peut dépasser en hauteur (générique qui défile)."""
    while True:
        layout = Layout(text, font, size, width, height, max_w=width * 0.88)
        too_wide = any(w > width * 0.88 for _, _, w in layout.line_boxes)
        too_tall = not allow_tall and layout.line_h * len(layout.lines) > height * 0.88
        if not (too_wide or too_tall) or size <= 12:
            return layout
        size = max(12, int(size * 0.92))


class Layout:
    """Découpe le texte en morceaux positionnés, chacun rattaché à un groupe de timing."""

    def __init__(self, text, font, size, width, height, max_w=None):
        self.font, self.size = font, size
        self._cache = {}
        self.lines = []
        for hard_line in text.split("\n"):  # sauts de ligne saisis (touche Entrée)
            self.lines += self.wrap(hard_line, max_w) if max_w else [hard_line]
        self.line_h = self.measure("Hg")[1]
        top = (height - self.line_h * len(self.lines)) // 2
        self.line_boxes = []  # (x, y, w) de chaque ligne
        for i, line in enumerate(self.lines):
            w = self.advance(line)
            self.line_boxes.append(((width - w) // 2, top + i * self.line_h, w))

    def wrap(self, line, max_w):
        """Retour à la ligne automatique, mot par mot."""
        words = line.split()
        if not words:
            return [""]
        out, current = [], words[0]
        for word in words[1:]:
            candidate = current + " " + word
            if self.measure(candidate)[0] <= max_w:
                current = candidate
            else:
                out.append(current)
                current = word
        out.append(current)
        return out

    def measure(self, s):
        if s not in self._cache:
            _, w, h, _, _ = Gimp.text_get_extents_font(s, self.size, self.font)
            self._cache[s] = (w, h)
        return self._cache[s]

    def advance(self, s):
        """Largeur d'avance de s, espaces de fin compris (Pango les ignore)."""
        if not s:
            return 0
        if s[-1].isspace():
            return self.measure(s + "|")[0] - self.measure("|")[0]
        return self.measure(s)[0]

    def pieces(self, unit):
        """Liste de dicts : text, x, y, w, line, ci (index du caractère), group, idx."""
        out, group = [], 0
        for li, line in enumerate(self.lines):
            lx, ly, lw = self.line_boxes[li]
            if unit in ("ligne", "bloc"):
                if line.strip():
                    out.append(dict(text=line, x=lx, y=ly, w=lw, line=li, ci=0,
                                    group=0 if unit == "bloc" else group))
                    group += 1
                continue
            i = 0
            while i < len(line):
                if line[i].isspace():
                    i += 1
                    continue
                j = i + 1
                if unit == "mot":
                    while j < len(line) and not line[j].isspace():
                        j += 1
                frag = line[i:j]
                out.append(dict(text=frag, x=lx + self.advance(line[:i]), y=ly,
                                w=self.measure(frag)[0], line=li, ci=i, group=group))
                group += 1
                i = j
        for idx, pc in enumerate(out):
            pc["idx"] = idx
        return out


def group_ranks(n, order):
    if order == "inverse":
        return [n - 1 - k for k in range(n)]
    if order == "centre":
        mid = (n - 1) / 2
        return [abs(k - mid) for k in range(n)]
    if order == "aleatoire":
        ranks = list(range(n))
        random.Random(7).shuffle(ranks)
        return ranks
    return list(range(n))


# ------------------------------------------------------------------ effets
# Chaque effet renvoie l'état d'un morceau pour une progression p (0..1) et sa
# valeur adoucie e : opacity, dx, dy, scale, clip (rectangle) et bar (rectangle).

def fx_fondu(pc, p, e, ctx):
    return dict(opacity=clamp(p * 1.5), dy=(1 - e) * ctx["slide"])


def fx_chute(pc, p, e, ctx):
    return dict(opacity=clamp(p * 4), dy=-(1 - e) * ctx["size"] * 2)


def fx_alterne(pc, p, e, ctx):
    sign = -1 if pc["group"] % 2 == 0 else 1
    return dict(opacity=clamp(p * 3), dy=sign * (1 - e) * ctx["size"] * 1.5)


def fx_glisser(pc, p, e, ctx):
    lx, ly, lw = ctx["layout"].line_boxes[pc["line"]]
    pad = ctx["size"]
    return dict(opacity=1.0 if p > 0 else 0.0, dy=(1 - e) * ctx["layout"].line_h * 1.1,
                clip=(lx - pad, ly, lw + 2 * pad, ctx["layout"].line_h))


def fx_rideau(pc, p, e, ctx):
    x, y, w, h = pc["x"] - 4, pc["y"], pc["w"] + 8, ctx["layout"].line_h
    ease = ctx["ease"]
    if p <= 0:
        return dict(opacity=0.0)
    if p < 0.5:  # le volet s'étire de gauche à droite et cache la zone
        bw = clamp(ease(p / 0.5), 0, 1.2) * w
        return dict(opacity=0.0, bar=(x, y, bw, h) if bw >= 1 else None)
    left = clamp(ease((p - 0.5) / 0.5), 0, 1) * w  # puis se retire vers la droite
    bar = (x + left, y, w - left, h) if w - left >= 1 else None
    return dict(opacity=1.0, bar=bar)


def fx_stomp(pc, p, e, ctx):
    return dict(opacity=clamp(p * 3), scale=max(0.05, 1 + (1 - e) * 2))


def fx_flou(pc, p, e, ctx):
    # Flou qui se dissipe + lettres écartées du centre de la ligne qui se resserrent.
    lx, ly, lw = ctx["layout"].line_boxes[pc["line"]]
    spread = (pc["x"] + pc["w"] / 2) - (lx + lw / 2)
    blur = round(max(0.0, 1 - e) * ctx["size"] * 0.22 * 2) / 2  # par pas de 0,5 px
    return dict(opacity=clamp(p * 1.3), dx=spread * 0.35 * (1 - e), blur=blur)


def noise(a, b):
    """Nombre pseudo-aléatoire stable (même rendu à chaque export)."""
    return random.Random(a * 7919 + b * 104729).random()


def fx_neon(pc, p, e, ctx):
    # Tube qui s'allume en grésillant, puis quelques micro-coupures une fois allumé.
    if p <= 0:
        return dict(opacity=0.0)
    if p < 1:
        on = noise(pc["group"], int(ctx["t"] * ctx["fps"])) < p ** 0.6
    else:
        on = noise(pc["group"], int(ctx["t"] * 8)) > 0.04
    return dict(opacity=1.0 if on else 0.18,
                extras=[dict(variant="glow", opacity=0.95 if on else 0.0)])


def fx_remplissage(pc, p, e, ctx):
    # D'abord le contour, puis la couleur monte du bas vers le haut des lettres.
    if p <= 0:
        return dict(opacity=0.0)
    fill = ctx["ease"](clamp((p - 0.3) / 0.7))
    lh = ctx["layout"].line_h
    extras = []
    if fill >= 0.999:
        extras.append(dict(opacity=1.0))
    elif fill > 0.001:
        extras.append(dict(opacity=1.0, clip=(pc["x"] - 8, pc["y"] + lh * (1 - fill),
                                              pc["w"] + 16, lh * fill + 1)))
    return dict(variant="outline", opacity=clamp(p / 0.25), extras=extras)


def fx_vitesse(pc, p, e, ctx):
    # Arrivée rapide depuis la gauche ; flou de mouvement proportionnel à la vitesse.
    travel = ctx["width"] * 0.7
    step = 0.02
    speed = abs(ctx["ease"](clamp(p + step)) - e) / step  # en « trajets » par unité de p
    px_per_frame = speed * travel / max(1e-6, ctx["dur"] * ctx["fps"])
    # pas de flou une fois presque arrivé (sinon il traîne pendant le petit rebond)
    mblur = 0 if p >= 1 or p <= 0 or px_per_frame < 4 else round(
        min(ctx["size"] * 1.2, px_per_frame))
    return dict(opacity=clamp(p * 4), dx=-(1 - e) * travel, mblur=mblur)


def fx_detourage(pc, p, e, ctx):
    # Le contour se dessine (75 % du temps), puis l'intérieur se remplit en fondu.
    if p <= 0:
        return dict(opacity=0.0)
    trace = ctx["ease"](clamp(p / 0.75))
    fill = clamp((p - 0.7) / 0.3)
    return dict(variant="trace:%.3f" % trace, opacity=1 - fill,
                extras=[dict(opacity=fill)] if fill > 0 else [])


EFFECT_FUNCS = {"fondu": fx_fondu, "chute": fx_chute, "alterne": fx_alterne,
                "glisser": fx_glisser, "rideau": fx_rideau, "stomp": fx_stomp,
                "flou": fx_flou, "neon": fx_neon, "remplissage": fx_remplissage,
                "vitesse": fx_vitesse, "detourage": fx_detourage}


# ------------------------------------------------------------------ sons
# Sons fabriqués par calcul (aucun fichier externe, donc aucun droit d'auteur).
SR = 44100


def _env(n, tau):
    return [math.exp(-i / (tau * SR)) for i in range(n)]


def snd_click(rng):
    n = int(0.03 * SR)
    env = _env(n, 0.004)
    f = rng.uniform(1800, 2600)
    amp = rng.uniform(0.5, 0.8)
    return [amp * env[i] * (0.6 * rng.uniform(-1, 1) + 0.4 * math.sin(2 * math.pi * f * i / SR))
            for i in range(n)]


def snd_thump(rng):
    n = int(0.18 * SR)
    out, phase = [], 0.0
    for i in range(n):
        t = i / SR
        phase += 2 * math.pi * (55 + 110 * math.exp(-t / 0.03)) / SR
        out.append(0.9 * math.exp(-t / 0.05) * math.sin(phase)
                   + 0.3 * math.exp(-t / 0.004) * rng.uniform(-1, 1))
    return out


def snd_pop(rng):
    n = int(0.07 * SR)
    out, phase = [], 0.0
    f0 = rng.uniform(550, 700)
    for i in range(n):
        t = i / SR
        phase += 2 * math.pi * (f0 * (0.5 + 0.5 * math.exp(-t / 0.02))) / SR
        out.append(0.5 * math.exp(-t / 0.018) * math.sin(phase))
    return out


def snd_tick(rng):
    n = int(0.02 * SR)
    f = rng.uniform(1200, 1600)
    return [0.45 * math.exp(-i / (0.003 * SR)) * math.sin(2 * math.pi * f * i / SR)
            for i in range(n)]


def snd_whoosh(rng, dur=0.45, amp=0.5):
    n = int(dur * SR)
    out, y = [], 0.0
    for i in range(n):
        x = i / n
        a = 0.02 + 0.2 * math.sin(math.pi * x) ** 2  # le filtre s'ouvre puis se referme
        y += a * (rng.uniform(-1, 1) - y)
        out.append(amp * 2.2 * y * math.sin(math.pi * x) ** 2)
    return out


def snd_bell(rng):
    n = int(0.8 * SR)
    return [0.35 * math.exp(-i / (0.25 * SR)) *
            (math.sin(2 * math.pi * 2093 * i / SR) + 0.4 * math.sin(2 * math.pi * 4186 * i / SR))
            for i in range(n)]


def snd_buzz(rng):
    """Grésillement de tube néon : bourdonnement 100 Hz haché de façon irrégulière."""
    n = int(0.45 * SR)
    out, on = [], True
    for i in range(n):
        if i % int(0.025 * SR) == 0:
            on = rng.random() < 0.7
        t = i / SR
        hum = math.sin(2 * math.pi * 100 * t) + 0.5 * math.sin(2 * math.pi * 200 * t)
        crackle = rng.uniform(-1, 1) * 0.4
        out.append((0.22 * hum + 0.12 * crackle) * (1.0 if on else 0.1) * min(1, (n - i) / 2000))
    return out


def snd_bloop(rng):
    """Goutte : note grave qui glisse vers le haut, comme une bulle."""
    n = int(0.3 * SR)
    out, phase = [], 0.0
    for i in range(n):
        t = i / SR
        phase += 2 * math.pi * (180 + 520 * (t / 0.3) ** 2) / SR
        out.append(0.55 * math.sin(phase) * math.sin(math.pi * min(1, t / 0.3)) ** 0.7
                   * math.exp(-t / 0.18))
    return out


def snd_shatter(rng):
    """Verre brisé : souffle aigu qui décroît, semé de petits éclats."""
    n = int(0.9 * SR)
    out, y = [], 0.0
    for i in range(n):
        t = i / SR
        x = rng.uniform(-1, 1)
        y = x - 0.85 * y  # filtre passe-haut grossier : son « cristallin »
        v = 0.35 * y * math.exp(-t / 0.25)
        if rng.random() < 0.002:  # éclats ponctuels
            v += rng.uniform(0.4, 0.8) * math.exp(-t / 0.4)
        out.append(v)
    return out


SOUNDS = {"bloop": snd_bloop, "shatter": snd_shatter, "click": snd_click, "thump": snd_thump, "pop": snd_pop, "tick": snd_tick,
          "whoosh": snd_whoosh, "whoosh_soft": lambda r: snd_whoosh(r, 0.35, 0.3),
          "whoosh_fast": lambda r: snd_whoosh(r, 0.22, 0.45),
          "bell": snd_bell, "buzz": snd_buzz}


def write_soundtrack(events, duration, path):
    """events : liste de (temps en s, nom du son). Écrit un WAV mono 16 bits."""
    rng = random.Random(11)
    total = int(duration * SR) + 1
    buf = [0.0] * total
    for t, name in events:
        start = int(t * SR)
        for i, v in enumerate(SOUNDS[name](rng)):
            if 0 <= start + i < total:
                buf[start + i] += v
    peak = max(1e-9, max(abs(v) for v in buf))
    gain = min(1.0, 0.85 / peak)
    samples = array.array("h", (int(v * gain * 32767) for v in buf))
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SR)
        wav.writeframes(samples.tobytes())


# ------------------------------------------------------------------ dialogue
def build_dialog(dialog, config):
    """Onglets « Écran 1-3 » (texte multiligne + effet), galerie d'effets animée,
    puis trois cadres côte à côte : Animation, Apparence, Sortie."""
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk

    textviews, tab_labels = [], {}
    for i in range(1, N_SCREENS + 1):
        tv = dialog.get_widget("text-%d" % i, Gtk.TextView)
        textviews.append(tv)
        props = ["effect-%d" % i, "unit-%d" % i, "easing-%d" % i]
        if i > 1:  # case « Inclure cet écran » : on peut le désactiver sans effacer le texte
            props.insert(0, "use-%d" % i)
        opts = dialog.fill_box("opts-%d" % i, props)
        page = dialog.fill_box("page-%d" % i, ["text-%d" % i, "opts-%d" % i])
        page.set_orientation(Gtk.Orientation.HORIZONTAL)
        page.set_spacing(12)
        tab_labels[i] = dialog.get_label("tab-%d" % i, T("Écran %d", "Screen %d") % i,
                                         False, False)
    notebook = dialog.fill_notebook("screens", ["tab-%d" % i for i in range(1, N_SCREENS + 1)],
                                    ["page-%d" % i for i in range(1, N_SCREENS + 1)])

    def update_tabs(*_):
        """Onglet d'un écran non utilisé (vide ou décoché) : « Écran 2 — inactif »."""
        for i, label in tab_labels.items():
            used = bool(config.get_property("text-%d" % i).strip()) and (
                i == 1 or config.get_property("use-%d" % i))
            label.set_text((T("Écran %d", "Screen %d") if used else
                            T("Écran %d — inactif", "Screen %d — off")) % i)
    config.connect("notify", update_tabs)
    update_tabs()
    top = dialog.fill_box("top", ["screens"])

    # Réglages secondaires dans des bulles flottantes (et non des sections dépliables) :
    # la fenêtre garde toujours la même taille, les boutons ne bougent jamais.
    timing_box = dialog.fill_box("timing-box", ["duration", "stagger", "hold", "scroll-time"])
    custom_box = dialog.fill_box("custom-box", ["width", "height"])

    columns_def = (
        ("anim", T("Animation", "Animation"), ["order", "exit", "cursor"]),
        ("look", T("Apparence", "Appearance"), ["font", "font-size", "text-color", "bg-color",
                                                "accent-color", "slide"]),
        ("out", T("Sortie", "Output"), ["size-preset", "fps", "format",
                                        "sound", "file-name"]),
    )
    frames, boxes = [], {}
    for key, title, props in columns_def:
        dialog.get_label(key + "-label", title, False, False)
        boxes[key] = dialog.fill_box(key + "-box", props)
        dialog.fill_frame(key + "-frame", key + "-label", False, key + "-box")
        frames.append(key + "-frame")
    add_folder_chooser(Gtk, config, boxes["out"])
    add_popover_button(Gtk, boxes["anim"], timing_box, len(boxes["anim"].get_children()),
                       T("Réglages avancés de la durée", "Advanced timing settings"),
                       T("Durée par élément, décalage, maintien, vitesse de défilement",
                         "Duration per element, delay, hold, scrolling speed"))
    add_popover_button(Gtk, boxes["out"], custom_box, 1,
                       T("Taille personnalisée", "Custom size"),
                       T("Largeur et hauteur utilisées avec le format « Personnalisée »",
                         "Width and height used with the “Custom” frame size"))
    columns = dialog.fill_box("columns", frames)
    columns.set_orientation(Gtk.Orientation.HORIZONTAL)
    columns.set_spacing(18)
    columns.set_homogeneous(False)
    dialog.fill(["top", "columns"])  # « run-mode » n'est volontairement pas affiché

    # Champs texte de 5 lignes, avec ascenseur. Entrée insère un saut de ligne
    # (un GtkTextView ne déclenche jamais le bouton Valider).
    for tv in textviews:
        if not isinstance(tv, Gtk.TextView):
            continue
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.set_tooltip_text(T("Texte de cet écran. Entrée = nouvelle ligne. "
                              "Laisser vide pour ne pas utiliser l'écran.",
                              "Text for this screen. Enter = new line. "
                              "Leave empty to skip this screen."))
        parent = tv.get_parent()
        if parent is not None:
            pos = parent.get_children().index(tv)
            parent.remove(tv)
            # Taille fixe (5 lignes) : le champ ne s'élargit plus avec une phrase longue,
            # le texte passe à la ligne tout seul (retour visuel, distinct de la touche Entrée).
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_shadow_type(Gtk.ShadowType.IN)
            scroll.set_propagate_natural_width(False)
            scroll.set_propagate_natural_height(False)
            line_h = tv.create_pango_layout("Ag").get_pixel_size()[1]
            scroll.set_size_request(460, 5 * line_h + 10)
            scroll.set_halign(Gtk.Align.START)
            scroll.add(tv)
            parent.pack_start(scroll, False, False, 0)
            parent.reorder_child(scroll, pos)
            for sibling in parent.get_children():  # l'espace libre va aux listes à droite
                parent.set_child_packing(sibling, sibling is not scroll, True, 0,
                                         Gtk.PackType.START)
            scroll.show_all()

    gallery = build_gallery(Gtk, config, notebook)
    top.pack_start(gallery, False, False, 6)
    gallery.show_all()


def add_popover_button(Gtk, box, content, position, label, tip):
    """Bouton « Libellé ▾ » qui ouvre une bulle flottante contenant des réglages."""
    button = Gtk.MenuButton()
    inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    inner.pack_start(Gtk.Label(label=label), False, False, 0)
    inner.pack_start(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.BUTTON),
                     False, False, 0)
    button.add(inner)
    button.set_tooltip_text(tip)
    button.set_halign(Gtk.Align.START)
    popover = Gtk.Popover.new(button)
    content.set_border_width(12)
    align_fields(Gtk, content)
    popover.add(content)
    button.set_popover(popover)
    box.pack_start(button, False, False, 4)
    box.reorder_child(button, position)
    button.show_all()
    content.show_all()


def align_fields(Gtk, box):
    """Aligne une colonne de réglages : toutes les étiquettes ont la même largeur et
    tous les champs numériques la même taille, donc les boutons − et + sont alignés."""
    labels = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
    fields = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)

    def first(widget, cls):
        if isinstance(widget, cls):
            return widget
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                found = first(child, cls)
                if found is not None:
                    return found
        return None

    for row in box.get_children():
        label, spin = first(row, Gtk.Label), first(row, Gtk.SpinButton)
        if label is not None:
            label.set_xalign(0.0)
            labels.add_widget(label)
        if spin is not None:
            spin.set_width_chars(6)
            fields.add_widget(spin)
    box._size_groups = (labels, fields)  # garde les groupes en vie avec la boîte


def add_folder_chooser(Gtk, config, box):
    """Ligne « Dossier d'enregistrement » avec un vrai sélecteur, placée avant le nom."""
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    label = Gtk.Label(label=T("Dossier d'enregistrement", "Save in folder"), xalign=0)
    chooser = Gtk.FileChooserButton(title=T("Choisir le dossier", "Choose the folder"),
                                    action=Gtk.FileChooserAction.SELECT_FOLDER)
    chooser.set_tooltip_text(T("Dossier où le fichier sera créé",
                               "Folder where the file will be created"))
    chooser.set_current_folder(folder_path(config.get_property("folder")))
    chooser.connect("file-set",
                    lambda c: config.set_property("folder", c.get_filename() or ""))
    row.pack_start(label, False, False, 0)
    row.pack_end(chooser, True, True, 0)
    box.pack_start(row, False, False, 0)
    box.reorder_child(row, len(box.get_children()) - 2)  # juste avant « Nom du fichier »
    row.show_all()


def build_gallery(Gtk, config, notebook):
    """Rangée de vignettes animées ; un clic choisit l'effet de l'écran affiché."""
    gi.require_version('Gdk', '3.0')
    from gi.repository import Gdk
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    # Une seule rangée de 5 vignettes par onglet ; les onglets sont sur la ligne du titre,
    # donc ajouter des effets n'augmente pas la hauteur de la fenêtre.
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    title = Gtk.Label(xalign=0)
    title.set_markup("<b>%s</b>  %s" % (
        T("Galerie d'effets", "Effects gallery"),
        T("— un clic applique l'effet à l'écran sélectionné",
          "— click to apply the effect to the selected screen")))
    header.pack_start(title, False, False, 0)
    switcher = Gtk.StackSwitcher()
    switcher.set_stack(stack)
    header.pack_end(switcher, False, False, 0)
    box.pack_start(header, False, False, 0)
    box.pack_start(stack, False, False, 0)
    rows, tab_of = {}, {}
    for t_index, (tab_title, nicks) in enumerate(GALLERY_TABS):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, homogeneous=True)
        stack.add_titled(row, "tab%d" % t_index, tab_title)
        for nick in nicks:
            rows[nick] = row
            tab_of[nick] = "tab%d" % t_index

    buttons, updating = {}, [False]

    def effect_key():
        return "effect-%d" % (notebook.get_current_page() + 1)

    def refresh(*_):
        updating[0] = True
        current = config.get_property(effect_key())
        for nick, button in buttons.items():
            button.set_active(nick == current)
        if current in tab_of:  # montre l'onglet qui contient l'effet de l'écran
            stack.set_visible_child_name(tab_of[current])
        updating[0] = False
        return False

    def on_toggled(button, nick):
        if updating[0]:
            return
        if button.get_active():
            config.set_property(effect_key(), nick)
        refresh()

    for nick, (label, tip) in EFFECTS.items():
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        button = Gtk.ToggleButton()
        # Vignette fixe (image prise en plein mouvement) ; l'animation se joue tant que
        # la souris survole la vignette, puis l'image fixe revient.
        still = os.path.join(HERE, "apercus", nick + ".png")
        anim = os.path.join(HERE, "apercus", nick + ".gif")
        still = still if os.path.exists(still) else anim
        if os.path.exists(still):
            image = Gtk.Image.new_from_file(still)
            inner.pack_start(image, False, False, 0)
            if os.path.exists(anim) and anim != still:
                def play(widget, event, img=image, f=anim):
                    img.set_from_file(f)  # repart du début de l'animation
                    return False

                def stop(widget, event, img=image, f=still):
                    # Gtk signale aussi une « sortie » vers les éléments internes du bouton
                    if event.detail != Gdk.NotifyType.INFERIOR:
                        img.set_from_file(f)
                    return False

                button.connect("enter-notify-event", play)
                button.connect("leave-notify-event", stop)
        inner.pack_start(Gtk.Label(label=label), False, False, 0)
        button.add(inner)
        button.set_tooltip_text(tip)
        button.connect("toggled", on_toggled, nick)
        rows[nick].pack_start(button, True, True, 0)
        buttons[nick] = button

    for row in set(rows.values()):  # cases vides : même largeur de vignette partout
        for _ in range(GALLERY_PER_ROW - len(row.get_children())):
            row.pack_start(Gtk.Box(), True, True, 0)

    notebook.connect("switch-page", lambda *_: GLib.idle_add(refresh))
    config.connect("notify", lambda *_: None if updating[0] else refresh())
    refresh()
    # Un Gtk.Stack ignore le choix de page tant que ses pages ne sont pas affichées :
    # on refait la sélection une fois la galerie visible (réouverture du dialogue).
    box.connect("map", lambda *_: GLib.idle_add(refresh))
    return box


# ------------------------------------------------------------------ écran d'attente
class Cancelled(Exception):
    """L'utilisateur a cliqué sur Annuler pendant la création."""


class WaitWindow:
    """Fenêtre affichée pendant la création : aperçu animé, grande barre de progression,
    étape en cours, temps restant estimé, bouton Annuler ; puis « Ouvrir le dossier »."""

    def __init__(self, effect):
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk, Gdk
        self.Gtk = Gtk
        self.cancelled, self.done, self.start = False, False, time.time()

        css = Gtk.CssProvider()
        css.load_from_data(b"progressbar trough, progressbar progress { min-height: 22px; }"
                           b" progressbar progress { background-image: none;"
                           b"   background-color: #2f8fff; border-color: #2f8fff; }"
                           b" progressbar text { font-size: 13pt; font-weight: bold; }")
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        win = Gtk.Window(title=T("Texte animé", "Animated text"))
        win.set_position(Gtk.WindowPosition.CENTER)
        # Attachée à la fenêtre de GIMP (comme ses propres dialogues) : au-dessus de GIMP
        # seulement, pas « toujours au premier plan » sur les autres programmes.
        try:
            from gi.repository import GimpUi
            GimpUi.window_set_transient(win)
        except Exception:
            pass
        win.set_resizable(False)
        win.set_default_size(540, -1)
        win.connect("delete-event", self.on_delete)
        self.win = win

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(24)
        win.add(box)
        gif = os.path.join(HERE, "apercus", effect + ".gif")
        if os.path.exists(gif):
            box.pack_start(Gtk.Image.new_from_file(gif), False, False, 0)
        self.title = Gtk.Label()
        self.title.set_markup("<span size='x-large' weight='bold'>%s</span>"
                              % T("Création de l'animation…", "Creating the animation…"))
        box.pack_start(self.title, False, False, 0)
        self.detail = Gtk.Label(label=T("Préparation…", "Preparing…"))
        self.detail.set_line_wrap(True)
        self.detail.set_max_width_chars(60)
        box.pack_start(self.detail, False, False, 0)
        self.bar = Gtk.ProgressBar(show_text=True)
        box.pack_start(self.bar, False, False, 4)
        self.eta = Gtk.Label()
        box.pack_start(self.eta, False, False, 0)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_halign(Gtk.Align.END)
        self.cancel_btn = Gtk.Button(label=T("Annuler", "Cancel"))
        self.cancel_btn.connect("clicked", lambda *_: self.cancel())
        self.open_btn = Gtk.Button(label=T("Ouvrir le dossier", "Open folder"))
        self.close_btn = Gtk.Button(label=T("Fermer", "Close"))
        self.close_btn.connect("clicked", lambda *_: self.close())
        for b in (self.open_btn, self.close_btn, self.cancel_btn):
            buttons.pack_start(b, False, False, 0)
        box.pack_start(buttons, False, False, 0)

        win.show_all()
        self.open_btn.hide()
        self.close_btn.hide()
        self.pump()

    def pump(self):
        while self.Gtk.events_pending():
            self.Gtk.main_iteration_do(False)

    def on_delete(self, *_):
        if self.done:
            self.close()
        else:
            self.cancel()
        return True

    def cancel(self):
        self.cancelled = True
        self.detail.set_text(T("Annulation…", "Cancelling…"))
        self.cancel_btn.set_sensitive(False)

    def update(self, fraction, text):
        """Appelée après chaque image ; renvoie False si l'utilisateur a annulé."""
        if not self.cancelled:
            fraction = clamp(fraction)
            self.bar.set_fraction(fraction)
            self.bar.set_text("%d %%" % round(fraction * 100))
            self.detail.set_text(text)
            elapsed = time.time() - self.start
            if fraction > 0.04 and elapsed > 2:
                left = elapsed * (1 - fraction) / fraction
                self.eta.set_text(T("Temps restant estimé : %s", "Estimated time left: %s")
                                  % (("%d s" % left) if left < 90 else
                                     ("%d min %02d s" % (left // 60, left % 60))))
        self.pump()
        return not self.cancelled

    def finished(self, out):
        """Affiche le résultat et attend que l'utilisateur ferme la fenêtre."""
        self.done = True
        self.title.set_markup("<span size='x-large' weight='bold'>%s</span>"
                              % T("Animation terminée ✓", "Animation complete ✓"))
        self.detail.set_text(out)
        self.bar.set_fraction(1.0)
        self.bar.set_text("100 %")
        self.eta.set_text(T("Durée de création : %d s", "Creation time: %d s")
                          % (time.time() - self.start))
        self.cancel_btn.hide()
        self.open_btn.connect("clicked", lambda *_: open_folder(out))
        self.open_btn.show()
        self.close_btn.show()
        self.close_btn.grab_focus()
        self.Gtk.main()  # jusqu'au clic sur « Fermer »

    def close(self):
        was_waiting = self.done
        self.win.destroy()
        self.pump()
        if was_waiting:
            self.Gtk.main_quit()


def open_folder(path):
    """Ouvre l'explorateur sur le fichier créé."""
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
    except OSError:
        pass


# ------------------------------------------------------------------ greffon
class TexteAnime(Gimp.PlugIn):

    def do_set_i18n(self, name):
        return False  # textes gérés par T() : pas de catalogue gettext

    def do_query_procedures(self):
        return [PROC_NAME]

    def do_create_procedure(self, name):
        Gegl.init(None)
        procedure = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_menu_label(T("Texte _animé…", "_Animated text…"))
        procedure.set_documentation(
            T("Anime le texte", "Animates text"),
            T("Jusqu'à 3 écrans de texte animé (fondu, machine à écrire, chute, alterné, "
              "glisser, rideau, stomp), exportés en MP4, WebP ou GIF.",
              "Up to 3 screens of animated text (fade, typewriter, drop, alternate, slide, "
              "wipe, stomp), exported as MP4, WebP or GIF."), name)
        procedure.set_attribution("maxim", "maxim", "2026")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.ALWAYS)
        procedure.add_menu_path("<Image>/File/Create/Animation")

        rw = GObject.ParamFlags.READWRITE

        def choice_arg(key, label, tip, values, default):
            choice = Gimp.Choice.new()
            for i, (nick, text) in enumerate(values.items()):
                text, help_ = text if isinstance(text, tuple) else (text, "")
                choice.add(nick, i, text, help_)
            procedure.add_choice_argument(key, label, tip, choice, default, rw)

        procedure.add_enum_argument("run-mode", "Mode", "", Gimp.RunMode,
                                    Gimp.RunMode.INTERACTIVE, rw)

        def mn(label, i):
            # Raccourci Alt+lettre seulement sur l'écran 1 (sinon doublons d'un onglet à l'autre)
            return label if i == 1 else label.replace("_", "")

        defaults = [T("Bonjour\nGIMP 3", "Hello\nGIMP 3"), "", ""]
        for i in range(1, N_SCREENS + 1):
            if i > 1:
                procedure.add_boolean_argument(
                    "use-%d" % i, T("Inclure cet écran", "Include this screen"),
                    T("Décochez pour ne pas utiliser cet écran sans effacer son texte. "
                      "Un écran sans texte est aussi ignoré.",
                      "Untick to leave this screen out without deleting its text. "
                      "A screen with no text is skipped too."), True, rw)
            procedure.add_string_argument(
                "text-%d" % i, T("Texte %d", "Text %d") % i,
                T("Texte de l'écran %d (vide = écran ignoré)",
                  "Text of screen %d (empty = screen skipped)") % i, defaults[i - 1], rw)
            choice_arg("effect-%d" % i, mn(T("_Effet", "_Effect"), i),
                       T("Animation de cet écran (voir aussi la galerie)",
                         "Animation for this screen (see also the gallery)"),
                       EFFECTS, ["fondu", "machine", "stomp"][i - 1])
            choice_arg("unit-%d" % i, mn(T("_Unité animée", "Animated _unit"), i),
                       T("Ce qui bouge séparément : chaque lettre, chaque mot, chaque ligne "
                         "ou tout le texte d'un bloc",
                         "What moves separately: each letter, word, line or the whole block"),
                       UNITS, "auto")
            choice_arg("easing-%d" % i, mn(T("Cour_be", "Eas_ing"), i),
                       T("Manière d'accélérer et de ralentir le mouvement",
                         "How the motion speeds up and slows down"), EASINGS, "auto")

        choice_arg("order", T("_Ordre", "_Order"),
                   T("Ordre d'apparition des éléments", "Order in which elements appear"),
                   ORDERS, "normal")
        procedure.add_boolean_argument(
            "exit", T("Sortie à la fin", "Exit at the end"),
            T("Fait disparaître le dernier écran en inversant son entrée. Les écrans "
              "suivis d'un autre écran ont toujours une sortie.",
              "Plays the last screen's entrance backwards to clear it. Screens followed "
              "by another screen always exit."), False, rw)
        procedure.add_boolean_argument(
            "cursor", T("Curseur (machine à écrire)", "Cursor (typewriter)"),
            T("Affiche un curseur clignotant pour l'effet Machine à écrire",
              "Shows a blinking cursor for the Typewriter effect"), True, rw)
        procedure.add_double_argument(
            "duration", T("_Durée par élément (s)", "_Duration per element (s)"),
            T("Temps que met chaque lettre, mot ou ligne à apparaître",
              "Time each letter, word or line takes to appear"), 0.05, 10.0, 0.6, rw)
        procedure.add_double_argument(
            "stagger", T("Déca_lage entre éléments (s)", "De_lay between elements (s)"),
            T("Attente entre le départ d'un élément et celui du suivant (effet cascade). "
              "Pour la machine à écrire : intervalle entre deux frappes.",
              "Wait between one element starting and the next (cascade). "
              "For the typewriter: interval between keystrokes."), 0.0, 5.0, 0.06, rw)
        procedure.add_double_argument(
            "hold", T("_Maintien (s)", "_Hold (s)"),
            T("Durée pendant laquelle le texte complet reste affiché",
              "How long the complete text stays on screen"), 0.0, 60.0, 1.5, rw)

        procedure.add_double_argument(
            "scroll-time", T("Traversée de l'écran (s)", "Screen crossing time (s)"),
            T("Générique et Bandeau uniquement : temps que met le texte pour traverser "
              "l'image. Plus la valeur est grande, plus le défilement est lent.",
              "Credits and Ticker only: time the text takes to cross the frame. "
              "Higher = slower scrolling."), 1.0, 120.0, 5.0, rw)

        procedure.add_font_argument("font", T("_Police", "_Font"), "", False, None, True, rw)
        procedure.add_int_argument("font-size", T("Ta_ille (px)", "S_ize (px)"),
                                   T("Hauteur du texte en pixels", "Text height in pixels"),
                                   8, 1000, 110, rw)
        procedure.add_color_argument("text-color", T("Couleur du te_xte", "Te_xt color"), "",
                                     True, hex_color("#ffffff"), rw)
        procedure.add_color_argument("bg-color", T("Couleur du _fond", "_Background color"), "",
                                     False, hex_color("#1e2a44"), rw)
        procedure.add_color_argument(
            "accent-color", T("Couleur d'accent", "Accent color"),
            T("Sert à trois effets : le volet du Rideau, le halo du Néon et le cadre de "
              "la Mise au point. Ignorée par les autres effets.",
              "Used by three effects: the Wipe panel, the Neon glow and the Focus frame. "
              "Ignored by other effects."), False, hex_color("#ff5a3c"), rw)
        procedure.add_int_argument(
            "slide", T("Montée du fondu (px)", "Fade rise (px)"),
            T("Effet Fondu uniquement : distance en pixels dont le texte remonte pendant "
              "qu'il apparaît. 0 = fondu sur place.",
              "Fade effect only: distance in pixels the text rises while fading in. "
              "0 = fade in place."), 0, 1000, 30, rw)

        choice_arg("size-preset", T("Format d'image", "Frame size"),
                   T("Dimensions de la vidéo ou de l'animation",
                     "Dimensions of the video or animation"),
                   {k: v[2] for k, v in SIZE_PRESETS.items()}, "carre")
        procedure.add_int_argument("width", T("Largeur (px)", "Width (px)"),
                                   T("Utilisée si le format est « Personnalisée »",
                                     "Used when the frame size is “Custom”"),
                                   16, 8192, 1080, rw)
        procedure.add_int_argument("height", T("Hauteur (px)", "Height (px)"),
                                   T("Utilisée si le format est « Personnalisée »",
                                     "Used when the frame size is “Custom”"),
                                   16, 8192, 1080, rw)
        procedure.add_int_argument("fps", T("Images par seconde", "Frames per second"),
                                   T("25 ou 30 pour la vidéo ; 12 à 15 allège un GIF",
                                     "25 or 30 for video; 12–15 makes a GIF lighter"),
                                   1, 60, 25, rw)
        choice_arg("format", T("Type de fichier", "File type"),
                   T("MP4 : réseaux sociaux et vidéo. WebP : web, léger. GIF : e-mail, "
                     "PowerPoint.", "MP4: social media and video. WebP: web, light. "
                     "GIF: email, PowerPoint."), FORMATS, "mp4")
        procedure.add_boolean_argument(
            "sound", T("Ajouter des sons (MP4)", "Add sounds (MP4)"),
            T("Ajoute des bruitages créés par le greffon (frappe, souffle, impact…). "
              "Uniquement pour le MP4 : le WebP et le GIF n'ont pas de son.",
              "Adds sound effects generated by the plug-in (keys, whoosh, impact…). "
              "MP4 only: WebP and GIF have no sound."), True, rw)
        # Dossier stocké en texte : un paramètre « fichier » de GIMP 3.2 est enregistré sous
        # Windows avec des « \ » que GIMP ne sait plus relire (plantage au lancement suivant).
        procedure.add_string_argument(
            "folder", T("Dossier d'enregistrement", "Save in folder"),
            T("Dossier où le fichier sera créé (Images si aucun n'est choisi)",
              "Folder where the file is created (Pictures if none is chosen)"), "", rw)
        procedure.add_string_argument(
            "file-name", T("Nom du fichier (sans extension)", "File name (no extension)"),
            T("Juste le nom, par exemple « intro ». L'extension .mp4, .webp ou .gif est "
              "ajoutée selon le type de fichier. Un fichier du même nom est remplacé.",
              "Just the name, e.g. “intro”. The .mp4, .webp or .gif extension is added "
              "from the file type. A file with the same name is replaced."),
            "texte-anime", rw)
        return procedure

    # ------------------------------------------------------------------ run
    def run(self, procedure, config, data):
        # GIMP 3.2 perd les couleurs par défaut à l'enregistrement : on les restaure.
        for key, default in (("text-color", "#ffffff"), ("bg-color", "#1e2a44"),
                             ("accent-color", "#ff5a3c")):
            color = config.get_property(key)
            if color is None or color.get_rgba()[3] == 0.0:
                config.set_property(key, hex_color(default))

        interactive = config.get_property("run-mode") == Gimp.RunMode.INTERACTIVE
        if interactive:
            gi.require_version('GimpUi', '3.0')
            from gi.repository import GimpUi
            GimpUi.init(PROC_NAME)
            dialog = GimpUi.ProcedureDialog(procedure=procedure, config=config,
                                            title=T("Texte animé", "Animated text"))
            build_dialog(dialog, config)
            ok = dialog.run()
            dialog.destroy()
            if not ok:
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        keys = ("order", "duration", "stagger", "hold", "scroll-time", "exit", "cursor",
                "slide", "font",
                "font-size", "text-color", "bg-color", "accent-color", "size-preset", "width",
                "height", "fps", "format", "sound")
        p = {k.replace("-", "_"): config.get_property(k) for k in keys}
        if p["size_preset"] != "perso":
            p["width"], p["height"], _ = SIZE_PRESETS[p["size_preset"]]
        screens = []
        for i in range(1, N_SCREENS + 1):
            if i > 1 and not config.get_property("use-%d" % i):
                continue  # écran décoché : ignoré, son texte est conservé
            text = config.get_property("text-%d" % i).replace("\\n", "\n").replace("\r", "")
            if text.strip():
                screens.append(dict(text=text.strip("\n"),
                                    effect=config.get_property("effect-%d" % i),
                                    unit=config.get_property("unit-%d" % i),
                                    easing=config.get_property("easing-%d" % i)))
        if not screens:
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                GLib.Error(T("Aucun texte saisi", "No text entered")))
        if p["font"] is None:
            p["font"] = default_font()
        if p["font"] is None:
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR,
                GLib.Error(T("Aucune police disponible", "No font available")))
        out = resolve_output(config.get_property("folder"), config.get_property("file-name"),
                             p["format"])
        if interactive and os.path.exists(out):  # en mode script, on remplace sans demander
            out = confirm_overwrite(out)
            if out is None:
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        wait = WaitWindow(screens[0]["effect"]) if interactive else None
        Gimp.context_push()
        try:
            scenes = [Scene(p, s, exit_on=(k < len(screens) - 1 or p["exit"]))
                      for k, s in enumerate(screens)]
            for a, b in zip(scenes, scenes[1:]):  # deux écrans Liquide : morphing de a vers b
                if a.effect == "liquide" and b.effect == "liquide":
                    a.morph_next = b
                    b.set_formed()
            renderer = Renderer(p, scenes)
            progress = wait.update if wait else None
            image = renderer.render(progress)
            ok, msg = renderer.export(image, out, progress)
        except Cancelled:
            if wait:
                wait.close()
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        finally:
            Gimp.context_pop()

        if not ok:
            if wait:
                wait.close()
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR,
                                               GLib.Error(msg))
        if interactive:
            wait.finished(out)  # reste ouvert jusqu'au clic sur « Fermer »
            Gimp.Display.new(image)
        else:
            Gimp.message(T("Animation exportée : ", "Animation exported: ") + out)
            image.delete()
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


# ------------------------------------------------------------------ écran
def gegl_filter(layer, operation, props):
    """Applique définitivement un filtre GEGL (avec ses réglages) à un calque."""
    flt = Gimp.DrawableFilter.new(layer, operation, operation)
    cfg = flt.get_config()
    for name, value in props.items():
        cfg.set_property(name, value)
    flt.update()
    layer.merge_filter(flt)


def apply_blur(layer, radius, pad):
    """Flou gaussien GEGL ; agrandit d'abord le calque de « pad » pixels de chaque côté,
    sinon le flou serait coupé net sur ses bords."""
    Gimp.Layer.resize(layer, layer.get_width() + 2 * pad, layer.get_height() + 2 * pad,
                      pad, pad)
    gegl_filter(layer, "gegl:gaussian-blur",
                {"std-dev-x": float(radius), "std-dev-y": float(radius)})


def frame_signature(items):
    """Résumé de ce qui sera dessiné : deux images au même résumé sont identiques."""
    sig = []
    for pc, st in items:
        bar = st.get("bar")
        bars = bar if isinstance(bar, list) else ([bar] if bar else [])
        sig.append((pc.get("idx", pc["text"]), pc.get("variant"),
                    round(pc["x"] + st.get("dx", 0)), round(pc["y"] + st.get("dy", 0)),
                    round(st.get("opacity", 1) * 100), round(st.get("scale", 1), 3),
                    st.get("blur", 0), st.get("mblur", 0), st.get("rot", 0),
                    tuple(round(v) for v in st["clip"]) if st.get("clip") else None,
                    tuple(tuple(round(v) for v in b) for b in bars)))
    return tuple(sig)


class Scene:
    """Un écran : son texte, son effet et sa chronologie (entrée, maintien, sortie)."""

    def __init__(self, p, screen, exit_on):
        self.p = p
        self.effect = screen["effect"]
        self.scroll = self.effect in SCROLL_EFFECTS
        self.exit = exit_on and not self.scroll  # un défilement sort de lui-même
        auto_unit, auto_ease = EFFECT_DEFAULTS[self.effect]
        forced = {"machine": "lettre", "generique": "ligne", "bandeau": "bloc",
                  "focus": "mot", "parallaxe": "ligne", "liquide": "bloc"}
        self.unit = forced.get(self.effect) or (
            auto_unit if screen["unit"] == "auto" else screen["unit"])
        self.ease_name = auto_ease if screen["easing"] == "auto" else screen["easing"]
        self.ease = EASE_FUNCS[self.ease_name]
        self.fps = p["fps"]
        self.dur = 1.0 / self.fps if self.effect == "machine" else p["duration"]
        # Durées minimales : en dessous, ces effets ne se lisent pas.
        minimum = {"neon": 1.2, "detourage": 1.5, "liquide": 1.2, "eclats": 1.0}
        self.dur = max(self.dur, minimum.get(self.effect, 0))

        if self.effect == "bandeau":  # une seule ligne, sans retour automatique
            text = "   •   ".join(l.strip() for l in screen["text"].split("\n") if l.strip())
            self.layout = Layout(text, p["font"], p["font_size"], p["width"], p["height"])
        else:
            self.layout = fit_layout(screen["text"], p["font"], p["font_size"], p["width"],
                                     p["height"], allow_tall=self.effect == "generique")
        self.size = self.layout.size  # peut être réduite pour que le texte tienne
        self.pieces = self.layout.pieces(self.unit)
        n_groups = max(pc["group"] for pc in self.pieces) + 1
        ranks = group_ranks(n_groups, p["order"])
        max_rank = max(ranks) if ranks else 0
        for pc in self.pieces:
            pc["rank"] = ranks[pc["group"]]
            pc["rank_out"] = max_rank - pc["rank"]  # sortie : dernier entré, premier sorti
        self.t_in = max_rank * p["stagger"] + self.dur
        self.t_hold_end = self.t_in + p["hold"]
        self.t_total = self.t_hold_end + (self.t_in if self.exit else 0)
        self.ctx = dict(size=self.size, slide=p["slide"], layout=self.layout,
                        ease=self.ease, fps=self.fps, width=p["width"], dur=self.dur, t=0.0)
        if self.scroll:
            self.setup_scroll()
        elif self.effect == "focus":
            self.setup_focus()
        elif self.effect == "parallaxe":
            self.setup_parallax()
        elif self.effect == "eclats":
            self.setup_shards()
        elif self.effect == "liquide":
            self.setup_liquid()

    # ---------------------------------------------------------- éclats
    def setup_shards(self):
        """Chaque élément est découpé en carreaux qui arrivent de loin en tournant."""
        W = self.p["width"]
        ts = max(12, int(self.size / 2.2))
        self.shards = []
        for pc in self.pieces:
            cols = int(math.ceil(pc["w"] / ts))
            rows = int(math.ceil(self.layout.line_h / ts))
            for j in range(rows):
                for i in range(cols):
                    seed = pc["idx"] * 1000 + j * 100 + i
                    angle = noise(seed, 1) * 2 * math.pi
                    dist = W * (0.12 + 0.35 * noise(seed, 2))
                    self.shards.append(dict(
                        text=pc["text"], x=pc["x"] + i * ts, y=pc["y"] + j * ts, w=ts,
                        line=pc["line"], group=pc["group"], rank=pc["rank"],
                        rank_out=pc["rank_out"], idx="%d-%d-%d" % (pc["idx"], i, j),
                        variant="frag:%d:%d:%d:%d" % (i * ts, j * ts, ts, ts),
                        vx=math.cos(angle) * dist, vy=math.sin(angle) * dist,
                        rot=(noise(seed, 3) - 0.5) * 2 * math.pi * 0.8,
                        jitter=noise(seed, 4) * 0.35))
        extra = 0.35 * self.dur  # les éclats ne partent pas tous en même temps
        self.t_in += extra
        self.t_hold_end = self.t_in + self.p["hold"]
        self.t_total = self.t_hold_end + (self.t_in if self.exit else 0)

    def shard_states(self, t):
        base = dict(opacity=1.0, dx=0.0, dy=0.0, scale=1.0, clip=None, bar=None)
        items = []
        for f in self.shards:
            pr = self.progress(f, t - f["jitter"] * self.dur)
            if pr <= 0:
                continue
            k = 1 - self.ease(pr)
            items.append((f, dict(base, opacity=clamp(pr * 2.5), dx=f["vx"] * k,
                                  dy=f["vy"] * k, rot=round(f["rot"] * k, 3))))
        return items, None

    # ---------------------------------------------------------- liquide
    def setup_liquid(self):
        """Gouttes floues + seuil : les lettres se forment comme du mercure.
        Si l'écran suivant est aussi Liquide, la sortie se transforme en son texte."""
        self.goo_r = self.size * 0.35
        self.morph_next, self.formed = None, False
        self.t_in = self.dur
        self.t_hold_end = self.t_in + self.p["hold"]
        self.t_total = self.t_hold_end + (self.dur if self.exit else 0)

    def set_formed(self):
        """Écran atteint par un morphing : il commence déjà formé (pas d'entrée)."""
        self.formed = True
        self.t_in = 0.0
        self.t_hold_end = self.p["hold"]
        self.t_total = self.t_hold_end + (self.dur if self.exit else 0)

    def liquid_states(self, t):
        base = dict(opacity=1.0, dx=0.0, dy=0.0, scale=1.0, clip=None, bar=None)
        R = self.goo_r
        if t < self.t_in:
            sets = [(self, (1 - self.ease(clamp(t / self.dur))) * R, 1.0)]
        elif t < self.t_hold_end or not self.exit:
            return [(pc, dict(base)) for pc in self.pieces], None  # texte net, normal
        else:
            q = self.ease(clamp((t - self.t_hold_end) / self.dur))
            if self.morph_next is None:  # simple fonte
                sets = [(self, q * R, 1.0)]
            else:  # morphing : le flou du départ monte, celui de l'arrivée descend
                sets = [(self, q * R, (1 - q) ** 2 if q > 0.5 else 1 - q * q),
                        (self.morph_next, (1 - q) * R, q * q if q < 0.5 else 1 - (1 - q) ** 2)]
        sets = [(sc, round(r * 2) / 2, round(wt, 2)) for sc, r, wt in sets]
        key = "goo:" + ",".join("%d:%.1f:%.2f" % (id(sc) % 997, r, wt) for sc, r, wt in sets)
        return [(dict(text="", idx="goo", x=0, y=0, w=0, line=0, variant=key, goo=sets),
                 dict(base))], None

    # ---------------------------------------------------------- mise au point
    def setup_focus(self):
        """Le texte apparaît flou ; un cadre se pose sur chaque mot (dans l'ordre choisi),
        qui devient net ; à la fin tout est net. Durée par élément = temps passé par mot."""
        self.dwell = max(self.dur, 0.4)
        self.focus_seq = sorted(self.pieces, key=lambda pc: (pc["rank"], pc["idx"]))
        self.focus_blur = "blur:%.1f" % max(1.0, round(self.size * 0.12 * 2) / 2)
        self.t_in = len(self.focus_seq) * self.dwell + 0.3
        self.t_hold_end = self.t_in + self.p["hold"]
        self.t_total = self.t_hold_end + (self.dur if self.exit else 0)

    def focus_rect(self, pc):
        pad = self.size * 0.15
        return (pc["x"] - pad, pc["y"], pc["w"] + 2 * pad, self.layout.line_h)

    def focus_states(self, t):
        base = dict(opacity=1.0, dx=0.0, dy=0.0, scale=1.0, clip=None, bar=None)
        if self.exit and t >= self.t_hold_end:  # sortie : tout redevient flou et s'efface
            fade = 1 - clamp((t - self.t_hold_end) / self.dur)
            return [(dict(pc, variant=self.focus_blur), dict(base, opacity=fade))
                    for pc in self.pieces], None
        k = int(t // self.dwell)
        if k >= len(self.focus_seq):  # toutes les mises au point faites : texte net
            return [(pc, dict(base)) for pc in self.pieces], None
        current = self.focus_seq[k]
        appear = clamp(t / 0.4)
        items = []
        for pc in self.pieces:
            if pc is current:
                items.append((pc, dict(base, opacity=appear)))
            else:
                items.append((dict(pc, variant=self.focus_blur), dict(base, opacity=0.55 * appear)))
        # Cadre : glisse du mot précédent vers le mot courant au début de chaque étape.
        x, y, w, h = self.focus_rect(current)
        local = (t - k * self.dwell) / self.dwell
        if k > 0 and local < 0.35:
            px, py, pw, ph = self.focus_rect(self.focus_seq[k - 1])
            e = ease_douce(local / 0.35)
            x, y, w, h = px + (x - px) * e, py + (y - py) * e, pw + (w - pw) * e, ph + (h - ph) * e
        th = max(2, round(self.size * 0.04))
        frame = [(x, y, w, th), (x, y + h - th, w, th), (x, y, th, h), (x + w - th, y, th, h)]
        items[0][1]["bar"] = frame
        return items, None

    # ---------------------------------------------------------- parallaxe
    def setup_parallax(self):
        """Lignes à trois profondeurs (vitesses différentes) + grand texte fantôme lent."""
        W, H = self.p["width"], self.p["height"]
        text = max(self.layout.lines, key=len).strip() or self.layout.lines[0]
        gsize = int(self.size * 2.6)
        _, gw, gh, _, _ = Gimp.text_get_extents_font(text, gsize, self.p["font"])
        self.ghost = dict(text=text, x=(W - gw) / 2, y=(H - gh) / 2, w=gw, line=0,
                          idx="fantome", size=gsize, group=-1)

    def parallax_states(self, t):
        W = self.p["width"]
        base = dict(opacity=1.0, dx=0.0, dy=0.0, scale=1.0, clip=None, bar=None)
        ghost_op = 0.06 * clamp(t / 0.6)
        if self.exit:
            ghost_op *= clamp((self.t_total - t) / 0.6)
        items = [(self.ghost, dict(base, opacity=ghost_op,
                                   dx=W * 0.25 - W * 0.5 * clamp(t / self.t_total)))]
        for pc in self.pieces:
            pr = self.progress(pc, t)
            depth = (1.0, 0.65, 0.4)[pc["line"] % 3]
            drift = -(t - self.t_total / 2) * W * 0.012 * depth  # dérive continue
            items.append((pc, dict(base, opacity=clamp(pr * 2),
                                   dx=(1 - self.ease(pr)) * W * 0.45 * depth + drift)))
        return items, None

    def setup_scroll(self):
        """Défilement : le texte entre par un bord et sort par l'autre.
        « Traversée » = temps pour parcourir la hauteur (ou largeur) de l'image."""
        W, H, cross = self.p["width"], self.p["height"], self.p["scroll_time"]
        boxes = self.layout.line_boxes
        if self.effect == "generique":
            top = boxes[0][1]
            block_h = self.layout.line_h * len(boxes)
            self.scroll_axis = "dy"
            self.scroll_from, self.scroll_to = H - top, -(top + block_h)
            self.t_total = cross * (1 + block_h / H)
        else:
            x0, _, w = boxes[0]
            self.scroll_axis = "dx"
            self.scroll_from, self.scroll_to = W - x0, -(x0 + w)
            self.t_total = cross * (1 + w / W)
        self.t_in = self.t_hold_end = self.t_total

    def scroll_states(self, t):
        e = self.ease(clamp(t / self.t_total))
        offset = self.scroll_from + (self.scroll_to - self.scroll_from) * e
        items = []
        for pc in self.pieces:
            st = dict(opacity=1.0, dx=0.0, dy=0.0, scale=1.0, clip=None, bar=None)
            st[self.scroll_axis] = offset
            items.append((pc, st))
        return items, (round(offset),), None

    def progress(self, pc, t):
        stagger = self.p["stagger"]
        if t < self.t_hold_end or not self.exit:
            return clamp((t - pc["rank"] * stagger) / self.dur)
        return 1 - clamp((t - self.t_hold_end - pc["rank_out"] * stagger) / self.dur)

    def frame_states(self, t):
        """(éléments à dessiner, signature pour repérer les images identiques, curseur)."""
        if self.effect == "machine":
            return self.typewriter_states(t)
        if self.scroll:
            return self.scroll_states(t)
        if self.effect == "focus":
            items, cursor = self.focus_states(t)
            return items, frame_signature(items), cursor
        if self.effect == "parallaxe":
            items, cursor = self.parallax_states(t)
            return items, frame_signature(items), cursor
        if self.effect == "eclats":
            items, cursor = self.shard_states(t)
            return items, frame_signature(items), cursor
        if self.effect == "liquide":
            items, cursor = self.liquid_states(t)
            return items, frame_signature(items), cursor
        items = []
        fx = EFFECT_FUNCS[self.effect]
        self.ctx["t"] = t
        for pc in self.pieces:
            pr = self.progress(pc, t)
            st = dict(opacity=1.0, dx=0.0, dy=0.0, scale=1.0, clip=None, bar=None, blur=0.0)
            st.update(fx(pc, pr, self.ease(pr), self.ctx))
            # Un effet peut dessiner plusieurs calques par élément (halo, contour…) :
            # « variant » choisit le rendu, « extras » ajoute des calques au même endroit.
            extras = st.pop("extras", [])
            variant = st.pop("variant", None)
            if st["opacity"] > 0.001 or st["bar"]:
                items.append((dict(pc, variant=variant) if variant else pc, st))
            for extra in extras:
                est = dict(st, clip=None, bar=None, blur=0.0)
                est.update(extra)
                v = est.pop("variant", None)
                if est["opacity"] > 0.001:
                    items.append((dict(pc, variant=v) if v else pc, est))
        return items, frame_signature(items), None

    def typewriter_states(self, t):
        visible = {}  # ligne -> nombre de caractères affichés
        last_line, n_vis = 0, 0
        for pc in self.pieces:
            if self.progress(pc, t) > 0:
                n_vis += 1
                visible[pc["line"]] = max(visible.get(pc["line"], 0), pc["ci"] + 1)
                last_line = max(last_line, pc["line"])
        typing = 0 < n_vis < len(self.pieces)  # curseur fixe pendant la frappe
        items = []
        for li, count in sorted(visible.items()):
            lx, ly, lw = self.layout.line_boxes[li]
            text = self.layout.lines[li][:count]
            items.append((dict(text=text, x=lx, y=ly, w=self.layout.advance(text), line=li),
                          dict(opacity=1.0, dx=0, dy=0, scale=1.0, clip=None, bar=None)))
        cursor_on = self.p["cursor"] and (typing or int(t * 2) % 2 == 0)
        cursor = None
        if cursor_on:
            lx, ly, _ = self.layout.line_boxes[last_line]
            x = lx + self.layout.advance(self.layout.lines[last_line][:visible.get(last_line, 0)])
            size = self.size
            lh = self.layout.line_h
            cursor = (x + size * 0.05, ly + (lh - size) / 2, max(2, size * 0.07), size)
        sig = tuple(sorted(visible.items())) + (cursor_on,)
        return items, sig, cursor

    def sound_events(self):
        """Bruitages (temps relatif à l'écran, nom du son) calés sur l'animation."""
        ev, stagger, dur = [], self.p["stagger"], self.dur
        if self.scroll:
            return [(0.0, "whoosh_soft")]
        groups = {}
        for pc in self.pieces:
            groups.setdefault(pc["group"], pc["rank"])
        starts = sorted(r * stagger for r in groups.values())
        if self.effect == "machine":
            ev += [(s, "click") for s in starts]
            ev.append((self.t_in + 0.05, "bell"))
            if self.exit:
                ev += [(self.t_hold_end + (max(groups.values()) - r) * stagger, "click")
                       for r in groups.values()]
            return ev
        if self.effect == "liquide":
            if not self.formed:
                ev.append((0.0, "bloop"))
            if self.exit:  # morphing vers l'écran suivant, ou fonte
                ev.append((self.t_hold_end, "bloop" if self.morph_next else "whoosh_soft"))
            return ev
        if self.effect == "eclats":
            ev.append((0.0, "whoosh"))
            if self.exit:
                ev.append((self.t_hold_end, "shatter"))
            return ev
        if self.effect == "chute":
            land = 0.364 if self.ease_name == "ricochet" else 0.7  # 1er contact au sol
            ev += [(s + dur * land, "tick") for s in starts]
        elif self.effect == "alterne":
            ev += [(s + dur * 0.3, "pop") for s in starts]
        elif self.effect == "stomp":
            ev += [(s + dur * 0.5, "thump") for s in starts]
        elif self.effect == "neon":
            ev += [(s, "buzz") for s in starts]
        elif self.effect == "focus":
            ev += [(k * self.dwell, "tick") for k in range(len(self.focus_seq))]
        elif self.effect == "vitesse" and len(starts) <= 12:
            ev += [(s, "whoosh_fast") for s in starts]
        elif self.unit == "lettre" or len(starts) > 8:  # beaucoup d'éléments : un seul souffle
            ev.append((0.0, "whoosh"))
        else:
            ev += [(s, "whoosh") for s in starts]
        if self.exit:
            ev.append((self.t_hold_end, "whoosh_soft"))
        return ev


# ------------------------------------------------------------------ rendu
class Renderer:
    """Fabrique les images de tous les écrans à la suite, puis exporte.

    L'image de travail garde un calque persistant par morceau : d'une image à
    l'autre on ne modifie que ce qui bouge, puis on capture le rendu visible.
    Les éléments éphémères (zoom, cache, volets, curseur) sont recréés à chaque image."""

    def __init__(self, p, scenes):
        self.p, self.scenes = p, scenes
        self.fps = p["fps"]
        self.starts, t = [], 0.0
        for sc in scenes:
            self.starts.append(t)
            t += sc.t_total
        self.t_total = t

    def glyph(self, text, size, variant=None):
        """Calque rendu une seule fois par (texte, taille, variante), dans une image cache.
        Variantes : None (texte), "glow" (halo néon flou, couleur d'accent),
        "outline" (contour seul), "blur:R" (texte flou de rayon R).
        Renvoie (calque, marge) : la marge ajoutée autour pour ne pas couper le flou."""
        key = (text, size, variant)
        if key not in self.glyphs:
            p, img = self.p, self.cache_img
            tl = Gimp.TextLayer.new(img, text, p["font"], size, Gimp.Unit.pixel())
            img.insert_layer(tl, None, 0)
            tl.set_color(p["accent_color"] if variant == "glow" else
                         Gegl.Color.new("white") if variant == "white" else p["text_color"])
            pad = 0
            if (variant or "").startswith("frag:"):
                # Éclat : un carreau du texte. Carreau vide (entre les lettres) -> rien.
                tx, ty, tw, th = (int(v) for v in variant[5:].split(":"))
                Gimp.Layer.resize(tl, tw, th, -tx, -ty)
                if tl.histogram(Gimp.HistogramChannel.ALPHA, 0.0, 1.0).mean < 1.0:
                    tl = None
            if variant == "outline":
                # Effacer dans un calque texte ne marche pas bien : on remplit un calque
                # normal avec la forme des lettres, puis on retire l'intérieur.
                ring = Gimp.Layer.new(img, "contour", tl.get_width(), tl.get_height(),
                                      Gimp.ImageType.RGBA_IMAGE, 100, Gimp.LayerMode.NORMAL)
                img.insert_layer(ring, None, 0)
                ring.set_offsets(*tl.get_offsets()[1:])
                img.select_item(Gimp.ChannelOps.REPLACE, tl)
                Gimp.context_set_foreground(p["text_color"])
                ring.edit_fill(Gimp.FillType.FOREGROUND)
                Gimp.Selection.shrink(img, max(2, round(size * 0.03)))
                ring.edit_clear()  # ne garde qu'un liseré de quelques pixels
                Gimp.Selection.none(img)
                tl = ring
            elif variant == "glow" or (variant or "").startswith("blur:"):
                radius = size * 0.16 if variant == "glow" else float(variant[5:])
                pad = int(math.ceil(radius * 3))
                apply_blur(tl, radius, pad)
            self.glyphs[key] = (tl, pad)
        return self.glyphs[key]

    def transient_text(self, scratch, text, size):
        tl = Gimp.TextLayer.new(scratch, text, self.p["font"], size, Gimp.Unit.pixel())
        scratch.insert_layer(tl, None, 0)
        tl.set_color(self.p["text_color"])
        self.transient.append(tl)
        return tl

    def draw_frame(self, scratch, si, scene, items, cursor):
        p = self.p
        w, h = p["width"], p["height"]
        for layer in self.transient:
            scratch.remove_layer(layer)
        self.transient = []

        bars, shown = [], set()
        for pc, st in items:
            if isinstance(st["bar"], list):
                bars.extend(st["bar"])
            elif st["bar"]:
                bars.append(st["bar"])
            if st["opacity"] <= 0.001:
                continue
            x, y = pc["x"] + st["dx"], pc["y"] + st["dy"]
            opacity = round(clamp(st["opacity"]) * 100, 1)
            size = pc.get("size", scene.size)
            variant = pc.get("variant")
            mode = Gimp.LayerMode.SCREEN if variant == "glow" else Gimp.LayerMode.NORMAL

            if (variant or "").startswith("trace:"):  # Tracé : contour dessiné en partie
                self.draw_trace(scratch, pc["text"], size, float(variant[6:]), x, y, opacity)
                continue
            if (variant or "").startswith("goo:"):  # Liquide : gouttes fusionnées
                tl = Gimp.Layer.new_from_drawable(self.goo_layer(pc["goo"]), scratch)
                scratch.insert_layer(tl, None, 0)
                self.transient.append(tl)
                continue
            if (variant or "").startswith("frag:") and \
                    self.glyph(pc["text"], size, variant)[0] is None:
                continue  # carreau vide (entre les lettres)

            blur = st.get("blur", 0.0)
            mblur = st.get("mblur", 0)
            if ("idx" in pc and st["scale"] == 1.0 and not st["clip"] and blur <= 0
                    and mblur <= 0 and not st.get("rot")):
                key = (si, pc["idx"], variant)
                shown.add(key)
                layer = self.persist.get(key)
                if layer is None:
                    src, pad = self.glyph(pc["text"], size, variant)
                    layer = Gimp.Layer.new_from_drawable(src, scratch)
                    scratch.insert_layer(layer, None, 0)
                    layer.set_mode(mode)
                    self.persist[key] = layer
                    self.persist_state[key] = None
                    self.persist_pad[key] = pad
                pad = self.persist_pad[key]
                state = (round(x) - pad, round(y) - pad, opacity)
                if self.persist_state[key] != state:
                    layer.set_offsets(state[0], state[1])
                    layer.set_opacity(opacity)
                    self.persist_state[key] = state
                if not layer.get_visible():
                    layer.set_visible(True)
                continue

            if st["scale"] != 1.0:  # zoom : texte recomposé à la taille voulue, centré
                tl = self.transient_text(scratch, pc["text"], size * st["scale"])
                cx = pc["x"] + pc["w"] / 2
                cy = pc["y"] + scene.layout.line_h / 2
                x = cx - tl.get_width() / 2 + st["dx"]
                y = cy - tl.get_height() / 2 + st["dy"]
            elif "idx" in pc:
                src, pad = self.glyph(pc["text"], size, variant)
                tl = Gimp.Layer.new_from_drawable(src, scratch)
                scratch.insert_layer(tl, None, 0)
                tl.set_mode(mode)
                self.transient.append(tl)
                x, y = x - pad, y - pad
            else:  # machine à écrire : sous-chaîne d'une ligne
                tl = self.transient_text(scratch, pc["text"], size)
            if blur > 0:
                pad = int(math.ceil(blur * 3))
                apply_blur(tl, blur, pad)
                x, y = x - pad, y - pad
            if mblur > 0:  # flou de mouvement horizontal (effet Traînée)
                pad = int(mblur)
                Gimp.Layer.resize(tl, tl.get_width() + 2 * pad, tl.get_height(), pad, 0)
                flt = Gimp.DrawableFilter.new(tl, "gegl:motion-blur-linear", "traînée")
                cfg = flt.get_config()
                cfg.set_property("length", float(mblur))
                cfg.set_property("angle", 0.0)
                flt.update()
                tl.merge_filter(flt)
                x -= pad
            tl.set_offsets(round(x), round(y))
            if st.get("rot"):  # éclat qui tourne (autour de son centre)
                tl.transform_rotate(st["rot"], True, 0, 0)
            tl.set_opacity(opacity)
            if st["clip"]:
                rect = clip_rect(*st["clip"], w, h)
                if rect is None:  # cache entièrement hors de l'image : rien de visible
                    tl.set_visible(False)
                else:
                    scratch.select_rectangle(Gimp.ChannelOps.REPLACE, *rect)
                    Gimp.Selection.invert(scratch)
                    tl.edit_clear()
                    Gimp.Selection.none(scratch)

        for key, layer in self.persist.items():
            if key not in shown and layer.get_visible():
                layer.set_visible(False)

        rects = [(r, p["accent_color"]) for r in bars]
        if cursor:
            rects.append((cursor, p["text_color"]))
        # Hors image, une sélection vide ferait remplir tout le calque (flash) : on borne.
        rects = [(clip_rect(*r, w, h), color) for r, color in rects]
        rects = [(r, color) for r, color in rects if r]
        if rects:
            top = Gimp.Layer.new(scratch, "formes", w, h, Gimp.ImageType.RGBA_IMAGE, 100,
                                 Gimp.LayerMode.NORMAL)
            scratch.insert_layer(top, None, 0)
            self.transient.append(top)
            for (rx, ry, rw, rh), color in rects:
                Gimp.context_set_foreground(color)
                scratch.select_rectangle(Gimp.ChannelOps.REPLACE, rx, ry, rw, rh)
                top.edit_fill(Gimp.FillType.FOREGROUND)
            Gimp.Selection.none(scratch)

    # ---------------------------------------------------------- tracé partiel
    def trace_polylines(self, text, size):
        """Contours des lettres en lignes brisées, avec longueurs cumulées (en cache)."""
        key = (text, size)
        if key not in self.polylines:
            src, _ = self.glyph(text, size)
            path = Gimp.Path.new_from_text_layer(self.cache_img, src)
            self.cache_img.insert_path(path, None, 0)
            polys = []
            for sid in path.get_strokes():
                coords, closed = path.stroke_interpolate(sid, 2.0)  # 1 point tous les 2 px
                pts = list(zip(coords[0::2], coords[1::2]))
                if closed and pts:
                    pts.append(pts[0])
                cum = [0.0]
                for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                    cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
                if len(pts) >= 2 and cum[-1] > 0:
                    polys.append((pts, cum))
            self.cache_img.remove_path(path)
            self.polylines[key] = polys
        return self.polylines[key]

    def draw_trace(self, scratch, text, size, fraction, x, y, opacity):
        """Trace chaque contour depuis son départ jusqu'à « fraction » de sa longueur."""
        if fraction <= 0:
            return
        w, h = self.p["width"], self.p["height"]
        path = Gimp.Path.new(scratch, "tracé")
        scratch.insert_path(path, None, 0)
        n_strokes = 0
        for pts, cum in self.trace_polylines(text, size):
            target = cum[-1] * fraction
            part = [pts[0]]
            for k in range(1, len(pts)):
                if cum[k] <= target:
                    part.append(pts[k])
                else:  # point intermédiaire exact sur le segment coupé
                    a = (target - cum[k - 1]) / max(1e-9, cum[k] - cum[k - 1])
                    part.append((pts[k - 1][0] + (pts[k][0] - pts[k - 1][0]) * a,
                                 pts[k - 1][1] + (pts[k][1] - pts[k - 1][1]) * a))
                    break
            if len(part) < 2:
                continue
            ctrl = []
            for px, py in part:  # polyligne en Bézier : chaque point est son propre levier
                ctrl += [px + x, py + y] * 3
            path.stroke_new_from_points(Gimp.PathStrokeType.BEZIER, ctrl, False)
            n_strokes += 1
        if n_strokes:
            layer = Gimp.Layer.new(scratch, "tracé", w, h, Gimp.ImageType.RGBA_IMAGE,
                                   opacity, Gimp.LayerMode.NORMAL)
            scratch.insert_layer(layer, None, 0)
            self.transient.append(layer)
            Gimp.context_set_stroke_method(Gimp.StrokeMethod.LINE)
            Gimp.context_set_line_width(max(2.0, size * 0.03))
            Gimp.context_set_foreground(self.p["text_color"])
            layer.edit_stroke_item(path)
        scratch.remove_path(path)

    # ---------------------------------------------------------- gouttes (liquide)
    def goo_layer(self, sets):
        """Chaque texte est rendu en blanc et flouté (rayon propre), les flous
        s'additionnent, puis un seuil redonne des bords nets : les formes fusionnent."""
        w, h = self.p["width"], self.p["height"]
        if self.goo_img is None:
            self.goo_img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
            self.goo_img.undo_disable()
        img = self.goo_img
        for layer in img.get_layers():
            img.remove_layer(layer)
        bg = Gimp.Layer.new(img, "noir", w, h, Gimp.ImageType.RGB_IMAGE, 100,
                            Gimp.LayerMode.NORMAL)
        img.insert_layer(bg, None, 0)
        Gimp.context_set_background(Gegl.Color.new("black"))
        bg.fill(Gimp.FillType.BACKGROUND)
        for scene, radius, weight in sets:
            # Fond noir opaque : l'intensité est portée par la couleur (et non par la
            # transparence), sinon les réglages de niveaux n'auraient aucun effet.
            group = Gimp.Layer.new(img, "texte", w, h, Gimp.ImageType.RGB_IMAGE, 100,
                                   Gimp.LayerMode.NORMAL)
            img.insert_layer(group, None, 0)
            group.fill(Gimp.FillType.BACKGROUND)
            for pc in scene.pieces:
                src, _ = self.glyph(pc["text"], scene.size, "white")
                c = Gimp.Layer.new_from_drawable(src, img)
                img.insert_layer(c, None, 0)
                c.set_offsets(round(pc["x"]), round(pc["y"]))
                group = img.merge_down(c, Gimp.MergeType.CLIP_TO_IMAGE)
            if radius > 0.4:
                gegl_filter(group, "gegl:gaussian-blur",
                            {"std-dev-x": float(radius), "std-dev-y": float(radius)})
                # Le flou dilue les traits fins (pic d'intensité bien sous 50 %) : on
                # remonte l'intensité pour garder des gouttes visibles et bien rondes.
                peak = clamp(scene.size * 0.11 / (2.5 * radius), 0.12, 1.0)
            else:
                peak = 1.0
            # « weight » : fondu enchaîné pendant le morphing (le texte qui part
            # n'épaissit plus celui qui arrive, et inversement).
            if peak < 1.0 or weight < 1.0:
                gegl_filter(group, "gegl:levels", {"in-low": 0.0, "in-high": peak,
                                                   "out-low": 0.0, "out-high": weight})
            group.set_mode(Gimp.LayerMode.ADDITION)
        flat = img.flatten()
        flat.add_alpha()
        # Seuil centré sur 50 % : à flou nul, les lettres gardent exactement leur graisse.
        gegl_filter(flat, "gegl:levels", {"in-low": 0.42, "in-high": 0.58,
                                          "out-low": 0.0, "out-high": 1.0})
        gegl_filter(flat, "gegl:color-to-alpha", {"color": Gegl.Color.new("black")})
        gegl_filter(flat, "gegl:color-overlay", {"value": self.p["text_color"]})
        return flat

    def scene_at(self, t):
        for si in range(len(self.scenes) - 1, -1, -1):
            if t >= self.starts[si]:
                return si
        return 0

    def render(self, progress=None):
        """progress(fraction, texte) -> False pour annuler (écran d'attente)."""
        p = self.p
        w, h = p["width"], p["height"]
        image = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
        image.undo_disable()
        scratch = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
        scratch.undo_disable()
        bg = Gimp.Layer.new(scratch, "fond", w, h, Gimp.ImageType.RGB_IMAGE, 100,
                            Gimp.LayerMode.NORMAL)
        scratch.insert_layer(bg, None, 0)
        Gimp.context_set_background(p["bg_color"])
        bg.fill(Gimp.FillType.BACKGROUND)
        self.cache_img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
        self.cache_img.undo_disable()
        self.glyphs, self.persist, self.persist_state, self.transient = {}, {}, {}, []
        self.persist_pad, self.polylines, self.goo_img = {}, {}, None

        self.frames = []  # [layer, durée en images]
        n_total = max(1, math.ceil(self.t_total * self.fps)) + 1
        prev_sig = None
        try:
            for f in range(n_total):
                t = f / self.fps
                si = self.scene_at(t)
                scene = self.scenes[si]
                items, sig, cursor = scene.frame_states(t - self.starts[si])
                sig = (si,) + sig
                if sig == prev_sig:  # image identique : on allonge la précédente
                    self.frames[-1][1] += 1
                    continue
                prev_sig = sig
                self.draw_frame(scratch, si, scene, items, cursor)
                layer = Gimp.Layer.new_from_visible(scratch, image, "image")
                image.insert_layer(layer, None, 0)
                self.frames.append([layer, 1])
                Gimp.progress_update(f / n_total)
                if progress and not progress(
                        0.8 * (f + 1) / n_total,
                        T("Écran %d / %d — image %d sur %d",
                          "Screen %d / %d — frame %d of %d")
                        % (si + 1, len(self.scenes), f + 1, n_total)):
                    raise Cancelled()
        except Cancelled:
            image.delete()
            raise
        finally:
            scratch.delete()
            self.cache_img.delete()
            if self.goo_img is not None:
                self.goo_img.delete()

        for i, (layer, count) in enumerate(self.frames):
            layer.set_name("%s %03d (%dms) (replace)" % (
                T("Image", "Frame"), i + 1, round(count * 1000 / self.fps)))
        image.undo_enable()
        return image

    # ---------------------------------------------------------- export
    def export(self, image, out, progress=None):
        fmt = self.p["format"]
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        if progress and fmt in ("webp", "gif"):
            # Export natif de GIMP : un seul appel bloquant, sans avancement intermédiaire.
            progress(0.85, T("Encodage du fichier %s… (peut prendre 30 secondes)",
                             "Encoding the %s file… (may take 30 seconds)") % fmt.upper())
        if fmt == "webp":
            ok = run_export_proc("file-webp-export", image, out, animation=True,
                                 animation_loop=True, quality=90.0,
                                 minimize_size=False)  # True : ~10x plus lent pour ~10 % gagnés
            return ok, T("Échec de l'export WebP", "WebP export failed")
        if fmt == "gif":
            ok = run_export_proc("file-gif-export", image, out, as_animation=True, loop=True)
            return ok, T("Échec de l'export GIF", "GIF export failed")

        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return False, T("ffmpeg introuvable (installer : winget install Gyan.FFmpeg)",
                            "ffmpeg not found (install: winget install Gyan.FFmpeg)")
        w, h = self.p["width"], self.p["height"]
        n_frames = sum(count for _, count in self.frames)
        wav = None
        if self.p["sound"]:
            events = [(self.starts[si] + t, name) for si, sc in enumerate(self.scenes)
                      for t, name in sc.sound_events()]
            fd, wav = tempfile.mkstemp(suffix=".wav", prefix="texte-anime-")
            os.close(fd)
            write_soundtrack(events, n_frames / self.fps, wav)

        # Les pixels de chaque image sont envoyés directement à ffmpeg (pas de fichiers
        # temporaires) ; une image tenue N fois est simplement réécrite N fois.
        cmd = [ffmpeg, "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (w, h),
               "-framerate", str(self.fps), "-i", "-"]
        if wav:
            cmd += ["-i", wav, "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "160k"]
        cmd += ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                "-movflags", "+faststart", out]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        rect = Gegl.Rectangle.new(0, 0, w, h)
        try:
            for i, (layer, count) in enumerate(self.frames):
                data = layer.get_buffer().get(rect, 1.0, "R'G'B' u8", Gegl.AbyssPolicy.CLAMP)
                for _ in range(count):
                    proc.stdin.write(data)
                if progress and not progress(
                        0.8 + 0.2 * (i + 1) / len(self.frames),
                        T("Encodage de la vidéo MP4…", "Encoding the MP4 video…")):
                    raise Cancelled()
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        except Cancelled:
            proc.kill()
            proc.wait()
            for path in (wav, out):  # pas de fichier à moitié écrit
                if path and os.path.exists(path):
                    os.remove(path)
            raise
        err = proc.stderr.read().decode("utf-8", "replace").strip()
        ok = proc.wait() == 0
        if wav:
            os.remove(wav)
        return ok, "ffmpeg : " + err


Gimp.main(TexteAnime.__gtype__, sys.argv)
