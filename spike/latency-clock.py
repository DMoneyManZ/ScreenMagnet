#!/usr/bin/env python3.13
"""
Millisecond clock for measuring end-to-end mirroring latency.

Put this on the monitor being mirrored, then photograph the Legion's screen and
the TV in one shot. The difference between the two readings IS the latency.

A phone camera works fine -- just take a photo with both screens in frame.

    python3.13 latency-clock.py

Positions itself at the top-left of the primary monitor (0,0), which is the
monitor doubletake crops to.
"""

import time
import tkinter as tk

BG = "#000000"
FG = "#00ff41"


class Clock(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("latency clock")
        self.configure(bg=BG)
        self.geometry("+0+0")
        self.attributes("-topmost", True)

        self.label = tk.Label(
            self, text="", font=("monospace", 96, "bold"), fg=FG, bg=BG, padx=40, pady=20
        )
        self.label.pack()

        self.hint = tk.Label(
            self,
            text="photograph this screen + the TV together — the difference is the latency",
            font=("sans", 13),
            fg="#888888",
            bg=BG,
        )
        self.hint.pack(pady=(0, 16))

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("q", lambda e: self.destroy())
        self.tick()

    def tick(self):
        t = time.time()
        # seconds.milliseconds -- rolls every 100s so the digits stay readable
        self.label.config(text=f"{int(t) % 100:02d}.{int((t % 1) * 1000):03d}")
        self.after(8, self.tick)


if __name__ == "__main__":
    Clock().mainloop()
