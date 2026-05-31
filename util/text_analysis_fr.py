#!/usr/bin/env python
"""
text_analysis_fr.py

French-specific text analysis module inheriting from BaseTextAnalysis.
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
        <b>Phrases complexes</b><br>
        Met en évidence les phrases très longues ou à structure compliquée, qui peuvent être difficiles à comprendre.<br>
        Envisagez de les diviser en phrases plus courtes et plus accessibles.
    """,
    "weak": """
        <b>Formulations faibles/voix passive</b><br>
        Indique les passages avec un langage imprécis ou peu affirmé.<br>
        Comprend:<br>
        - Les formulations faibles (expressions vagues ou indécises)<br>
        - La voix passive (phrases où le sujet ne fait pas l'action)<br>
        Exemple: 'La balle a été lancée' vs 'Jean a lancé la balle'<br>
        Les deux peuvent rendre le texte moins direct.
    """,
    "nonstandard": """
        <b>Verbes de dialogue non standard</b><br>
        Signale les verbes inhabituels décrivant la parole<br>
        (au lieu des verbes courants comme 'dire').<br>
        Des verbes trop créatifs peuvent dérouter le lecteur.
    """,
    "filter": """
        <b>Mots filtres</b><br>
        Désigne les mots qui affaiblissent le message<br>
        (comme 'juste', 'vraiment', 'littéralement').<br>
        Les supprimer renforcera la clarté du texte.
    """,
    "telling": """
        <b>Dire plutôt que montrer</b><br>
        Met en évidence les passages où les émotions ou les actions sont énoncées directement<br>
        au lieu de les montrer par des descriptions ou des actions.<br>
        Cela peut réduire l'engagement du lecteur.
    """,
    "weak_verb": """
        <b>Verbes faibles</b><br>
        Désigne les verbes sans charge émotionnelle claire.<br>
        Les remplacer par des synonymes plus forts donnera vie au texte.
    """,
    "overused": """
        <b>Mots suremployés</b><br>
        Indique les mots qui se répètent trop souvent.<br>
        Utilisez des synonymes ou modifiez la structure de la phrase pour varier.
    """,
    "pronoun": """
        <b>Références pronominales ambiguës</b><br>
        Signale les pronoms ('il', 'elle', 'ce', 'ils') dont le contexte est flou.<br>
        L'utilisation claire des pronoms évite les malentendus.
    """,
    "repetitive": """
        <b>Débuts de phrases répétitifs</b><br>
        Indique les séquences de phrases commençant de la même façon.<br>
        La diversité des débuts de phrases maintient l'attention du lecteur.
    """
}

FRENCH_DATA = {
    "passive_deps": {"aux:pass", "nsubj:pass"},
    "agent_markers": {"par"},
    "weak_patterns": [r'\b\w+(?:e|é)\b'],
    "weak_terms": {"peut-être", "probablement", "sans doute", "semble", "comme si", "un peu", "légèrement"},
    "standard_speech_verbs": {"dire", "demander"},
    "speech_verbs": {"dire", "demander", "chuchoter", "crier", "murmurer", "s'exclamer", "hurler"},
    "filter_words": {"voyait", "entendait", "sentait", "remarquait", "pensait", "se demandait", "observait", "regardait", "écoutait", "ressentait", "décidait", "considérait", "semblait", "apparaissait", "percevait", "imaginait"},
    "telling_verbs": {"être", "se sentir", "sembler", "paraître", "apparaître", "devenir"},
    "emotion_words": {"en colère", "triste", "heureux", "excité", "nerveux", "terrifié", "inquiet", "gêné", "déçu", "frustré", "irrité", "anxieux", "effrayé", "joyeux", "déprimé", "malheureux", "extatique", "contrarié", "furieux", "ravi", "choqué", "surpris", "confus", "fier", "content", "satisfait", "enthousiaste", "jaloux"},
    "weak_verbs": {"être", "avoir", "faire"},
    "common_words": {"et", "à", "de", "le", "la", "les", "un", "une", "des", "ce", "cette", "ces", "mon", "ton", "son", "notre", "votre", "leur", "en", "dans", "sur", "pour", "avec", "par", "pas", "ne", "que", "qui", "quoi", "où", "quand", "comment", "pourquoi", "si", "ou", "mais", "donc", "car", "comme", "lorsque", "puisque"},
    "quote_pattern": r'«[^»]*»|\'[^\']*\'|"[^"]*"'
}

class FrenchTextAnalysis(BaseTextAnalysis, QObject):
    # Emitted when the spaCy model has finished loading
    model_loaded: pyqtSignal = pyqtSignal()

    def __init__(self):
        BaseTextAnalysis.__init__(self, "fr_core_news_sm", FRENCH_DATA)
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
        msgBox.setText("The model 'fr_core_news_sm' was not found. Do you want to download it?")
        msgBox.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        return msgBox.exec() == QMessageBox.StandardButton.Yes

    def download_and_load_model(self):
        """
        Downloads the spaCy model and loads it. Emits a signal when the model is loaded.
        """
        try:
            spacy.cli.download('fr_core_news_sm')
            self.nlp = spacy.load('fr_core_news_sm')
            self.model_loaded.emit()
        except Exception as e:
            print(f"Error during model download: {e}")
        finally:
            self.download_in_progress = False

    def calculate_readability(self, text):
        """
        Calculates the readability for French using the Flesch Reading Ease adapted for French.
        Formula: 206.835 - (1.015 * ASL) - (73.6 * ASW)
        ASL = Average Sentence Length (words)
        ASW = Average Syllables per Word
        
        Higher scores indicate easier readability (opposite of Fog Index).
        """
        words = text.split()
        num_words = len(words)
        sentences = re.split(r'[.!?]+', text)
        sentences = [s for s in sentences if s.strip()]
        num_sentences = len(sentences)

        # Estimate syllables (simplified approach)
        def count_syllables(word):
            # Count vowel groups as an approximation for French syllables
            vowels = "aeiouyàâäéèêëîïôöùûüÿæœ"
            word = word.lower()
            count = 0
            in_vowel_group = False

            for char in word:
                if char in vowels:
                    if not in_vowel_group:
                        count += 1
                        in_vowel_group = True
                else:
                    in_vowel_group = False

            # Handle silent e at the end
            if word.endswith('e') and len(word) > 1 and word[-2] not in vowels:
                count = max(1, count - 1)

            # Ensure at least one syllable
            return max(1, count)

        total_syllables = sum(count_syllables(word) for word in words)

        # Avoid division by zero
        if num_sentences == 0 or num_words == 0:
            return 0

        asl = num_words / num_sentences
        asw = total_syllables / num_words

        # Flesch Reading Ease adapted for French
        # Scale is 0-100, where higher is easier to read
        score = 206.835 - (1.015 * asl) - (73.6 * asw)

        # Clamp the score to a reasonable range
        return max(0, min(100, score))

    def get_tooltips(self):
        """Returns tooltips in French."""
        return TOOLTIP_TRANSLATIONS

nlp = None

def initialize():
    """
    Initializes the French text analysis module.
    """
    global nlp
    analysis = FrenchTextAnalysis()
    if analysis.initialize():
        nlp = analysis.nlp
        return True
    return False

def comprehensive_analysis(text, target_grade=8):
    """
    Performs a comprehensive analysis of the given text.
    """
    analysis = FrenchTextAnalysis()
    if not analysis.initialize():
        raise RuntimeError("French spaCy model has not been loaded.")
    return analysis.comprehensive_analysis(text, target_grade)
