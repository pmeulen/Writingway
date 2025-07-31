from settings.llm_worker import LLMWorker
from PyQt5.QtCore import QObject, pyqtSignal
import traceback

class SummaryService(QObject):
    summary_generated = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None  # Initialize single worker

    def generate_summary(self, prompt, content, overrides):
        """Generate summary using LLM with a single worker."""
        try:
            # Initialize worker if not already created
            if self.worker is None:
                self.worker = LLMWorker("", {})  # Create with dummy params
                print(f"DEBUG: Created single LLMWorker: {id(self.worker)}")
                self.worker.data_received.connect(self._on_data_received)
                self.worker.finished.connect(self._on_finished)

            # Reset worker state
            if self.worker.isRunning():
                print(f"DEBUG: Waiting for worker {id(self.worker)} to stop")
                self.worker.wait(2000)  # Timeout to prevent hanging

            final_prompt = f"### User {prompt.get('text')}\n\nContent:\n{content}"
            merged_overrides = {
                "provider": prompt.get("provider", ""),
                "model": prompt.get("model", ""),
                "max_tokens": prompt.get("max_tokens", 2000),
                "temperature": prompt.get("temperature", 1.0),
                **overrides
            }
            print(f"DEBUG: Resetting worker for prompt: {final_prompt[:50]}...")
            # Assuming LLMWorker has a reset method or we set parameters directly
            # If LLMWorker doesn't support reset, we update its internal state
            self.worker.prompt = final_prompt  # Adjust based on LLMWorker implementation
            self.worker.overrides = merged_overrides
            self.worker.start()
            print(f"DEBUG: Started LLMWorker: {id(self.worker)}")
        except Exception as e:
            print(f"DEBUG: Error in generate_summary: {str(e)}")
            traceback.print_exc()
            self.error_occurred.emit(f"Failed to generate summary: {str(e)}")
            self.finished.emit()  # Allow continuation on error

    def _on_data_received(self, text):
        print(f"DEBUG: Emitting summary_generated for text: {text[:50]}...")
        self.summary_generated.emit(text)

    def _on_finished(self):
        print(f"DEBUG: Emitting finished for worker: {id(self.worker)}")
        self.finished.emit()  # Emit finished signal

    def cleanup_worker(self):
        """Clean up the worker at the end of all scenes."""
        if self.worker:
            worker_id = id(self.worker)
            if self.worker.isRunning():
                print(f"DEBUG: Waiting for worker {worker_id} to stop")
                self.worker.wait(2000)
            try:
                self.worker.data_received.disconnect()
                self.worker.finished.disconnect()
                print(f"DEBUG: Disconnected signals for worker {worker_id}")
            except TypeError:
                print(f"DEBUG: Signals already disconnected for worker {worker_id}")
            self.worker.deleteLater()
            print(f"DEBUG: Scheduled deletion for worker {worker_id}")
            self.worker = None
            print(f"DEBUG: Completed cleanup for worker {worker_id}")