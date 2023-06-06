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

def start_sampling(sdr, fsps, N):
    print("Sampling started...")
    RF_record_start_time = time.time()
    samples = sdr.read_samples(N)  # Collect N samples
    RF_record_end_time = time.time()
    print("Sampling stopped...")
    RF_record_duration_actual = RF_record_end_time - RF_record_start_time
    print("Actual time duration of RF recording:", RF_record_duration_actual)
    print("Commanded samples per second:", fsps)
    print("Actual samples per second:", N / RF_record_duration_actual)
    print("Percentage deviation:", (-100 * (fsps - (N / RF_record_duration_actual)) / fsps))
    spectrum = np.fft.fftshift(np.fft.fft(samples))
    return spectrum

def play_audio(myaudio, faudiosps, outputfile):
    print("Playing audio...")
    start_time = time.time()
    sd.play(10 * myaudio, faudiosps, blocking=True)
    end_time = time.time()
    time_actual = end_time - start_time
    print("Actual time duration to play audio:", time_actual)
    wav.write(outputfile, faudiosps, myaudio.astype(np.float32))
    result = model.transcribe("{outputfile}".format(outputfile=outputfile), fp16=False,)
    print(result["text"])

def main():
    sdr = RtlSdr()
    sdr.sample_rate = 2*256*256*16
    sdr.gain = 'auto'

    fsps = 2 * 256 * 256 * 16
    faudiosps = 48000
    sample_time = None

    spectrum = None
    is_sampling = False

    while True:
        user_input = input("Enter 'start' to begin sampling or 'stop' to stop and play audio: ")

        if user_input.lower() == 'start':
            if not is_sampling:
                fc_input = float(input("Enter the center frequency (in MHz): "))
                sample_time = int(input("Enter the amount of time you want to sample (in sec): "))
                sample_time = round(fsps * sample_time)
                sdr.center_freq = fc_input * 1e6
                spectrum = start_sampling(sdr, fsps, sample_time)
                is_sampling = True
            else:
                print("Sampling already in progress. Enter 'stop' to stop and play audio.")

        elif user_input.lower() == 'stop':
            if is_sampling:
                is_sampling = False
                if spectrum is not None:
                    fcutoff = 200000
                    bpm = taperedbandpassmask(sample_time,fsps,fcutoff,200000)
                    filteredspectrum = spectrum * bpm
                    filteredsignal = np.fft.ifft(np.fft.fftshift(filteredspectrum)) 
                    print("completed tapered bandpass mask")

                    w0 = 1030000/(fsps/2)
                    Q = 1
                    b, a = signal.iirnotch(w0,Q)
                    filteredsignal = signal.lfilter(b, a, filteredsignal)
                    print("complete iirnotch filtering")

                    theta = np.arctan2(filteredsignal.imag,filteredsignal.real)
                    derivthetap0 = np.convolve([1,-1],theta,'same')
                    derivthetapp = np.convolve([1,-1],(theta+np.pi) % (2*np.pi),'same')

                    derivtheta = np.zeros(len(derivthetap0))
                    for i in range(len(derivthetap0)):
                        if (abs(derivthetap0[i])<abs(derivthetapp[i])):
                            derivtheta[i] = derivthetap0[i] 
                        else:
                            derivtheta[i] = derivthetapp[i] 
                    cdtheta = copy(derivtheta)

                    spikethresh = 2
                    for i in range(1,len(derivtheta)-1):
                        if (abs(derivtheta[i])>spikethresh):
                            cdtheta[i] = (derivtheta[i-1]+derivtheta[i+1])/2.0

                    dsf = round(fsps/faudiosps)
                    dscdtheta = cdtheta[::dsf]

                    dscdtheta2 = copy(dscdtheta)
                    for i in range(len(dscdtheta2)):
                        dscdtheta2[i] = np.sum(cdtheta[i*dsf:(i+1)*dsf])/dsf
                    dscdtheta = copy(dscdtheta2)
                    myaudio = dscdtheta
                    outputfile = input("Enter the output file name (including .wav extension): ")
                    play_audio(myaudio, faudiosps, outputfile)                  
            else:
                print("No sampling in progress. Enter 'start' to begin sampling.")
        else:
            print("Invalid input. Enter 'start' to begin sampling or 'stop' to stop and play audio.")

def taperedbandpassmask(N,fsps,fcutoff,xwidth):
    fcutoff_n = fcutoff / fsps # fcutoff, normalized
    xwidth_n = xwidth / fsps # transition width, normalized
    
    pbfw = round(2*fcutoff_n*N)
    xbw = round(xwidth_n*N)
    sbw = int((N-pbfw-xbw-xbw)/2)
    # print("N=  ", N, " fsps= ",fsps, " fcutoff=", fcutoff, " fcutoff_n= ",fcutoff_n," xwidth= ",xwidth," xwidth_n= ",xwidth_n," pbfw= ", pbfw, " sbw= ", sbw)
    res = np.concatenate((np.zeros(sbw), #
                          np.arange(0.0,1.0,1.0/xbw), #
                          np.ones(pbfw), #
                          np.arange(1.0,0.0,-1.0/xbw), #
                          np.zeros(sbw)))
    # print("N = ",N)
    # print("xbw= ",xbw)
    # print("total sbw+xbw+pbfw+xbw+sbw= ",sbw+xbw+pbfw+xbw+sbw)
    # print("len(arange) = ", len(np.arange(0.0,1.0,1.0/xbw)))
    return(res)


if __name__ == '__main__':
    os.environ['KMP_DUPLICATE_LIB_OK']='True'
    model = whisper.load_model("small")
    main()
