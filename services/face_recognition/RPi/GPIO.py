import tkinter as tk
import threading
import time

# Mock constants matching the real RPi.GPIO interface
BCM = "BCM"
OUT = "OUT"
HIGH = 1
LOW = 0

# Internal pin state tracking
_pin_states = {}

class _LEDGUI:
    def __init__(self):
        # Start the Tkinter UI on a daemon thread
        self.thread = threading.Thread(target=self._setup_ui, daemon=True)
        self.thread.start()

        # Wait until the UI is initialized
        while not hasattr(self, "canvas"):
            time.sleep(0.01)

    def _setup_ui(self):
        self.root = tk.Tk()
        self.root.title("GPIO Simulator")

        self.canvas = tk.Canvas(self.root, width=200, height=120)
        self.canvas.pack()

        # Draw Blue LED (pin 27)
        self.blue_circle = self.canvas.create_oval(
            20, 20, 80, 80, fill="gray", outline="black"
        )
        self.canvas.create_text(50, 90, text="Blue LED", font=("Arial", 10))

        # Draw Green LED (pin 17)
        self.green_circle = self.canvas.create_oval(
            120, 20, 180, 80, fill="gray", outline="black"
        )
        self.canvas.create_text(150, 90, text="Green LED", font=("Arial", 10))

        # Ensure clicking the window close button exits the mainloop
        self.root.protocol("WM_DELETE_WINDOW", self.root.quit)

        self.root.mainloop()

    def set_led(self, pin, state):
        """
        Update the LED’s color. Called from GPIO.output().
        Schedule the actual itemconfig() via `after()` so it runs in the UI thread.
        """
        def _update():
            if pin == 27:  # Blue LED
                color = "blue" if state == HIGH else "gray"
                self.canvas.itemconfig(self.blue_circle, fill=color)
            elif pin == 17:  # Green LED
                color = "green" if state == HIGH else "gray"
                self.canvas.itemconfig(self.green_circle, fill=color)

        try:
            self.root.after(0, _update)
        except Exception:
            pass  # If UI is already closed, ignore


# Instantiate the simulator at import time
_gui = _LEDGUI()


def setmode(mode):
    # No-op in simulation (suppress print)
    pass

def setwarnings(flag):
    # No-op in simulation (suppress print)
    pass

def setup(pin, mode):
    # Initialize pin state to LOW (no print)
    _pin_states[pin] = LOW

def output(pin, state):
    # Update internal state and the simulated LED
    _pin_states[pin] = state
    _gui.set_led(pin, state)

def cleanup():
    # Clear internal state
    _pin_states.clear()
    # Exit the Tk mainloop, then destroy the window
    try:
        _gui.root.quit()
    except Exception:
        pass
    try:
        _gui.root.destroy()
    except Exception:
        pass
