from copy import copy
import numpy as np
from rtlsdr import RtlSdr
import sounddevice as sd
import time as time
from scipy import signal
import whisper
import scipy.io.wavfile as wav
import os
import tkinter as tk
from tkinter import filedialog
from tkinter import Spinbox
import threading
import queue

FSPS = 2 * 256 * 256 * 16
FAUDIOSPS = 48000

def start_sampling(N):
    global spectrum, is_sampling
    status_label.config(text="Sampling Started...")
    start_button.config(state=tk.DISABLED)
    stop_button.config(state=tk.DISABLED)
    samples = sdr.read_samples(N)
    stop_button.config(state=tk.NORMAL)
    status_label.config(text="Sampling Stopped...")
    spectrum = np.fft.fftshift(np.fft.fft(samples))
    status_label.config(text="Sampling Complete")

def play_audio_threaded(myaudio, outputfile):
    def play_audio(myaudio, outputfile):
        stop_button.config(state=tk.DISABLED)
        start_button.config(state=tk.DISABLED)
        status_label.config(text="Playing Audio...")
        sd.play(10 * myaudio, FAUDIOSPS, blocking=True)
        wav.write(outputfile, FAUDIOSPS, myaudio.astype(np.float32))
        status_label.config(text="Transcribing Audio...")
        threading.Thread(target=transcribe_audio, args=(outputfile,), daemon=True).start()
        

    threading.Thread(target=play_audio, args=(myaudio, outputfile), daemon=True).start()

def transcribe_audio(outputfile):
    result = model.transcribe(outputfile, fp16=False)
    transcribe_label.config(text="Transcribed Text: " + result["text"])
    status_label.config(text="Press 'Start Sampling' to Begin")
    stop_button.config(state=tk.NORMAL)
    start_button.config(state=tk.NORMAL)

def start_sampling_gui():
  global is_sampling
  if not is_sampling:
    stop_button.config(state=tk.DISABLED)
    fc_input = float(center_freq_spinbox.get())
    sample_time = int(sample_time_spinbox.get())
    sample_time = round(FSPS * sample_time)
    sdr.center_freq = fc_input * 1e6
    threading.Thread(target=start_sampling, args=(sample_time,), daemon=True).start()
  else:
    print("Sampling already in progress, please wait...")


def stop_sampling_gui(N):
    global spectrum, is_sampling
    if not is_sampling:
        fcutoff = 200000
        bpm = taperedbandpassmask((N*FSPS), FSPS, fcutoff, 200000)
        filteredspectrum = spectrum * bpm
        filteredsignal = np.fft.ifft(np.fft.fftshift(filteredspectrum))
        status_label.config(text="Complete TBM")

        w0 = 1030000 / (FSPS / 2)
        Q = 1
        b, a = signal.iirnotch(w0, Q)
        filteredsignal = signal.lfilter(b, a, filteredsignal)
        status_label.config(text="Complete IIR Notch Filtering")

        status_label.config(text="Processing...")
        threading.Thread(target=processing, args=(filteredsignal,), daemon=True).start()

    else:
        print("Sampling in progress, please wait...")

def processing(filteredsignal):
    theta = np.arctan2(filteredsignal.imag, filteredsignal.real)
    derivthetap0 = np.convolve([1, -1], theta, 'same')
    derivthetapp = np.convolve([1, -1], (theta + np.pi) % (2 * np.pi), 'same')

    derivtheta = np.zeros(len(derivthetap0))
    for i in range(len(derivthetap0)):
        if abs(derivthetap0[i]) < abs(derivthetapp[i]):
            derivtheta[i] = derivthetap0[i]
        else:
            derivtheta[i] = derivthetapp[i]
    cdtheta = copy(derivtheta)

    spikethresh = 2
    for i in range(1, len(derivtheta) - 1):
        if abs(derivtheta[i]) > spikethresh:
            cdtheta[i] = (derivtheta[i - 1] + derivtheta[i + 1]) / 2.0

    dsf = round(FSPS / FAUDIOSPS)
    dscdtheta = cdtheta[::dsf]

    dscdtheta2 = copy(dscdtheta)
    for i in range(len(dscdtheta2)):
        dscdtheta2[i] = np.sum(cdtheta[i * dsf:(i + 1) * dsf]) / dsf
    dscdtheta = copy(dscdtheta2)

    myaudio = dscdtheta
    outputfile = filedialog.asksaveasfilename(defaultextension=".wav", filetypes=[("WAV files", "*.wav")])
    audio_file_label.config(text="Audio File: " + outputfile)
    threading.Thread(target=play_audio_threaded, args=(myaudio, outputfile), daemon=True).start()
    print("Output file:", outputfile)


def taperedbandpassmask(N,fsps,fcutoff,xwidth):
    fcutoff_n = fcutoff / fsps # fcutoff, normalized
    xwidth_n = xwidth / fsps # transition width, normalized
    
    pbfw = round(2*fcutoff_n*N)
    xbw = round(xwidth_n*N)
    sbw = int((N-pbfw-xbw-xbw)/2)
    res = np.concatenate((np.zeros(sbw), #
                          np.arange(0.0,1.0,1.0/xbw), #
                          np.ones(pbfw), #
                          np.arange(1.0,0.0,-1.0/xbw), #
                          np.zeros(sbw)))
    return(res)

root = tk.Tk()
root.title("RF Sampling GUI")

# Create the necessary GUI components
center_freq_label = tk.Label(root, text="Center Frequency (MHz):")
center_freq_label.pack()
center_freq_spinbox = Spinbox(root, from_=88, to=108, increment=0.1, width=10)
center_freq_spinbox.pack()

sample_time_label = tk.Label(root, text="Sample Time (sec):")
sample_time_label.pack()
sample_time_spinbox = Spinbox(root, from_=5, to=60, increment=1, width=10)
sample_time_spinbox.pack()

start_button = tk.Button(root, text="Start Sampling", command=start_sampling_gui)
start_button.pack()

stop_button = tk.Button(root, text="Process and Play Audio", command=lambda: stop_sampling_gui(int(sample_time_spinbox.get())))
stop_button.pack()

status_label = tk.Label(root, text="Press 'Start Sampling' to Begin")
status_label.pack()

audio_file_label = tk.Label(root, text="Audio File: ")
audio_file_label.pack()

transcribe_label = tk.Label(root, text="Transcribed Text: ")
transcribe_label.pack()

# Initialize variables
sdr = RtlSdr()
sdr.sample_rate = 2 * 256 * 256 * 16
sdr.gain = 'auto'

spectrum = None
is_sampling = False
processing_queue = queue.Queue()


model = whisper.load_model("small")

root.mainloop()
