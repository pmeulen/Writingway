#!/usr/bin/env python
"""
text_analysis_es.py

Spanish-specific text analysis module inheriting from BaseTextAnalysis.
"""

import re
import threading

import spacy
import spacy.cli
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QMessageBox

from .base_text_analysis import BaseTextAnalysis

TOOLTIP_TRANSLATIONS = {
    "complex": """
        <b>Oraciones complejas</b><br>
        Destaca oraciones muy largas o con estructuras complicadas que pueden ser difíciles de entender.<br>
        Considera dividirlas en oraciones más cortas y más accesibles.
    """,
    "weak": """
        <b>Expresiones débiles/voz pasiva</b><br>
        Señala fragmentos de texto con lenguaje impreciso o poco asertivo.<br>
        Incluye:<br>
        - Expresiones débiles (frases ambiguas o indecisas)<br>
        - Voz pasiva (oraciones donde el sujeto no realiza la acción)<br>
        Ejemplo: 'La pelota fue lanzada' vs 'Juan lanzó la pelota'<br>
        Ambos pueden hacer que el texto sea menos directo.
    """,
    "nonstandard": """
        <b>Verbos de habla no estándar</b><br>
        Indica verbos inusuales que describen el habla<br>
        (en lugar de comunes como 'dijo').<br>
        Los verbos demasiado creativos pueden confundir al lector.
    """,
    "filter": """
        <b>Palabras filtro</b><br>
        Señala palabras que debilitan el mensaje<br>
        (como 'justamente', 'realmente', 'literalmente').<br>
        Eliminarlas fortalecerá la claridad del texto.
    """,
    "telling": """
        <b>Contar en lugar de mostrar</b><br>
        Destaca fragmentos donde las emociones o acciones se indican directamente<br>
        en lugar de mostrarlas a través de descripciones o acciones.<br>
        Esto puede reducir la participación del lector.
    """,
    "weak_verb": """
        <b>Verbos débiles</b><br>
        Señala verbos sin una carga emocional clara.<br>
        Reemplazarlos con sinónimos más fuertes animará el texto.
    """,
    "overused": """
        <b>Palabras sobreutilizadas</b><br>
        Indica palabras que se repiten con demasiada frecuencia.<br>
        Usa sinónimos o cambia la estructura de la oración para variar.
    """,
    "pronoun": """
        <b>Referencias pronominales poco claras</b><br>
        Señala pronombres ('él', 'ella', 'ello', 'ellos') con contexto poco claro.<br>
        El uso claro de pronombres evita malentendidos.
    """,
    "repetitive": """
        <b>Inicios de oraciones repetitivos</b><br>
        Indica secuencias de oraciones que comienzan de la misma manera.<br>
        La variedad en los comienzos de las oraciones mantiene la atención del lector.
    """
}

SPANISH_DATA = {
    "passive_deps": {"aux:pass", "nsubj:pass"},
    "agent_markers": {"por"},
    "weak_patterns": [r'\b\w+(?:mente)\b'],
    "weak_terms": {"quizás", "tal vez", "probablemente", "posiblemente", "parece", "como si", "un poco", "algo"},
    "standard_speech_verbs": {"decir", "preguntar"},
    "speech_verbs": {"decir", "preguntar", "susurrar", "gritar", "murmurar", "exclamar"},
    "filter_words": {"vio", "oyó", "sintió", "notó", "pensó", "se preguntó", "observó", "miró", "escuchó", "percibió", "decidió", "consideró", "parecía", "apareció", "imaginó"},
    "telling_verbs": {"ser", "estar", "sentirse", "parecer", "lucir", "aparecer", "volverse"},
    "emotion_words": {"enojado", "triste", "feliz", "emocionado", "nervioso", "asustado", "preocupado", "avergonzado", "decepcionado", "frustrado", "irritado", "inquieto", "aterrorizado", "alegre", "deprimido", "infeliz", "extático", "molesto", "furioso", "encantado", "conmocionado", "sorprendido", "confundido", "orgulloso", "contento", "satisfecho", "entusiasta", "celoso"},
    "weak_verbs": {"ser", "estar", "haber", "tener"},
    "common_words": {"y", "en", "a", "de", "para", "con", "por", "o", "pero", "si", "como", "es", "son", "fue", "era", "tiene", "tienen", "esto", "este", "esta", "estos", "estas", "aquel", "aquella", "aquello", "aquellos", "aquellas", "mi", "tu", "su", "nuestro", "vuestro", "sus", "se", "no", "sí", "porque", "cuando", "pues", "que", "cual", "cuales"},
    "quote_pattern": r'«[^»]*»|"[^"]*"'
}

class SpanishTextAnalysis(BaseTextAnalysis, QObject):
    # Emitted when the spaCy model has finished loading
    model_loaded: pyqtSignal = pyqtSignal()

    def __init__(self):
        BaseTextAnalysis.__init__(self, "es_core_news_sm", SPANISH_DATA)
        QObject.__init__(self)
        self.download_in_progress = False

    def initialize(self):
        """
        Initializes the spaCy model. If the model is not found, prompts the user to download it.
        """
        if super().initialize():
            return True
        if not self.download_in_progress and self.ask_for_download():
            self.download_in_progress = True
            threading.Thread(target=self.download_and_load_model, daemon=True).start()
        return False

    def ask_for_download(self):
        """
        Asks the user if they want to download the missing spaCy model.
        """
        msgBox = QMessageBox()
        msgBox.setWindowTitle("spaCy Model")
        msgBox.setText("The model 'es_core_news_sm' was not found. Do you want to download it?")
        msgBox.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        return msgBox.exec() == QMessageBox.StandardButton.Yes

    def download_and_load_model(self):
        """
        Downloads the spaCy model and loads it. Emits a signal when the model is loaded.
        """
        try:
            spacy.cli.download('es_core_news_sm')
            self.nlp = spacy.load('es_core_news_sm')
            self.model_loaded.emit()
        except Exception as e:
            print(f"Error during model download: {e}")
        finally:
            self.download_in_progress = False

    def calculate_readability(self, text):
        """
        Calculates the readability for Spanish using the Fernández-Huerta readability formula.
        """
        words = text.split()
        num_words = len(words)
        sentences = re.split(r'[.!?]+', text)
        sentences = [s for s in sentences if s.strip()]
        num_sentences = len(sentences)

        # Count syllables for Spanish
        syllables = 0
        for word in words:
            word = word.lower()
            # Remove punctuation
            word = re.sub(r'[^\w\s]', '', word)
            if not word:
                continue

            # Count syllables by counting vowel groups
            vowels = "aeiouáéíóúüy"
            count = 0
            prev_is_vowel = False

            for char in word:
                is_vowel = char in vowels
                if is_vowel and not prev_is_vowel:
                    count += 1
                prev_is_vowel = is_vowel

            # Ensure each word has at least one syllable
            syllables += max(1, count)

        if num_sentences == 0 or num_words == 0:
            return 0

        # Fernández-Huerta formula: 206.84 - 0.60 * P - 1.02 * F
        # P = average number of syllables per 100 words
        # F = average sentence length in words
        P = (syllables / num_words) * 100
        F = num_words / num_sentences

        return 206.84 - (0.60 * P) - (1.02 * F)

    def get_tooltips(self):
        """Returns tooltips in Spanish."""
        return TOOLTIP_TRANSLATIONS

nlp = None

def initialize():
    """
    Initializes the Spanish text analysis module.
    """
    global nlp
    analysis = SpanishTextAnalysis()
    if analysis.initialize():
        nlp = analysis.nlp
        return True
    return False

def comprehensive_analysis(text, target_grade=8):
    """
    Performs a comprehensive analysis of the given text.
    """
    analysis = SpanishTextAnalysis()
    if not analysis.initialize():
        raise RuntimeError("Spanish spaCy model has not been loaded.")
    return analysis.comprehensive_analysis(text, target_grade)
