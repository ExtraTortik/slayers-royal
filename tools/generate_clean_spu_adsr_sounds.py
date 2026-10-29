#!/usr/bin/env python3
"""
Скрипт синтеза чистых звуковых эффектов слот-машины Slayers Royal (PS1).
Эмулирует аппаратное затухание PS1 SPU ADSR (Attack-Decay-Sustain-Release)
для базового сэмпла vag_00, устраняя паразитный 1.8-секундный хвост
с хлюпающими и чавкающими звуками из мини-игры «Обед в таверне».
"""

import os
import shutil
import subprocess
import wave
import numpy as np

BASE_DIR = "/home/samvel/Downloads/Telegram Desktop/Slayers Royal"
SRC_VAG00 = "/home/samvel/dddd/data/smini_vag/vag_00.wav"
if not os.path.exists(SRC_VAG00):
    SRC_VAG00 = os.path.join(BASE_DIR, "ОРИГИНАЛЬНЫЕ_ЗВУКИ_СЛОТ_МАШИНЫ/01_сырые_сэмплы_SPU_VAG/vag_00.wav")

OUT_DIR_05 = os.path.join(BASE_DIR, "ОРИГИНАЛЬНЫЕ_ЗВУКИ_СЛОТ_МАШИНЫ/05_чистые_звуки_без_хлюпанья_SPU_ADSR")
OUT_DIR_GAME = os.path.join(BASE_DIR, "game/audio")
OUT_DIR_SLOT = os.path.join(BASE_DIR, "SLOT_AUDIO")

SOUND_SPECS = [
    {
        "id": 0,
        "name_ru": "01_остановка_барабана_чистый_C4",
        "name_en": "sfx_00_vag00_n60",
        "note": "C4 (60)",
        "ratio": 1.0,
        "rate": 22050,
        "aliases_game": ["sfx_00_vag00_n60"],
    },
    {
        "id": 7,
        "name_ru": "02_запуск_спина_чистый_G4",
        "name_en": "sfx_07_spin_vag00_n67",
        "note": "G4 (67)",
        "ratio": 1.498307,
        "rate": 33038,
        "aliases_game": ["sfx_07_spin_vag00_n67", "sfx_07_vag00_n67", "sfx_spin_07"],
    },
    {
        "id": 5,
        "name_ru": "03_победа_чистый_F4",
        "name_en": "sfx_05_victory_vag00_n65",
        "note": "F4 (65)",
        "ratio": 1.334840,
        "rate": 29433,
        "aliases_game": ["sfx_05_victory_vag00_n65", "sfx_victory_05"],
    },
    {
        "id": 6,
        "name_ru": "04_проигрыш_чистый_Fis4",
        "name_en": "sfx_06_fail_vag00_n66",
        "note": "F#4 (66)",
        "ratio": 1.414214,
        "rate": 31183,
        "aliases_game": ["sfx_06_fail_vag00_n66", "sfx_fail_06"],
    },
    {
        "id": 1,
        "name_ru": "05_клик_чистый_Cis4",
        "name_en": "sfx_01_click_vag00_n61",
        "note": "C#4 (61)",
        "ratio": 1.059463,
        "rate": 23361,
        "aliases_game": ["sfx_01_click_vag00_n61", "sfx_click_01"],
    },
]


def generate_clean_audio():
    print(f"Загрузка исходного сэмпла: {SRC_VAG00}")
    with wave.open(SRC_VAG00, "rb") as w:
        sample_rate = w.getframerate()
        n_channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)

    print(f"Исходный формат: {sample_rate} Гц, {n_channels}ch, {sampwidth*8}-bit, сэмплов: {len(raw)} ({len(raw)/sample_rate:.3f}с)")

    # 1. Поиск начала первого импульса (устранение начальной тишины 0.118с)
    threshold = 100
    above_thresh = np.where(np.abs(raw) > threshold)[0]
    if len(above_thresh) == 0:
        raise ValueError("Не найден импульс в сэмпле!")
    start_sample = int(above_thresh[0])
    print(f"Обнаружен фронт импульса на сэмпле {start_sample} (t = {start_sample / sample_rate:.4f} с)")

    # 2. Выделение 100 мс (2205 сэмплов при 22050 Гц)
    target_samples = int(sample_rate * 0.100) # 2205 сэмплов
    clean_slice = raw[start_sample : start_sample + target_samples].astype(np.float64)

    # 3. Наложение гладкого затухания ADSR (25 мс, 551 сэмпл, окно Hann / raised cosine)
    fade_len = int(sample_rate * 0.025) # 551 сэмпл
    fade_window = 0.5 * (1.0 + np.cos(np.linspace(0, np.pi, fade_len)))
    clean_slice[-fade_len:] *= fade_window

    clean_int16 = np.round(clean_slice).astype(np.int16)

    # Создаём выходные папки
    os.makedirs(OUT_DIR_05, exist_ok=True)
    os.makedirs(OUT_DIR_GAME, exist_ok=True)
    os.makedirs(OUT_DIR_SLOT, exist_ok=True)

    # Сохраняем базовый clean WAV в 05_чистые_звуки
    vag00_clean_wav = os.path.join(OUT_DIR_05, "vag_00_clean.wav")
    with wave.open(vag00_clean_wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(clean_int16.tobytes())
    print(f"Создан базовый чистый сэмпл: {vag00_clean_wav} ({len(clean_int16)} сэмплов, {len(clean_int16)/sample_rate*1000:.1f} мс)")

    # Базовый чистый OGG
    vag00_clean_ogg = os.path.join(OUT_DIR_05, "vag_00_clean.ogg")
    subprocess.run([
        "ffmpeg", "-y", "-i", vag00_clean_wav,
        "-c:a", "libvorbis", "-q:a", "6", vag00_clean_ogg
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Генерация каждого питчеванного звука
    for spec in SOUND_SPECS:
        name_ru = spec["name_ru"]
        rate_spu = spec["rate"]
        print(f"\nГенерация SoundID {spec['id']}: {name_ru} (Pitch {spec['note']}, {rate_spu} Гц)")

        wav_05 = os.path.join(OUT_DIR_05, f"{name_ru}.wav")
        ogg_05 = os.path.join(OUT_DIR_05, f"{name_ru}.ogg")

        if rate_spu == 22050:
            cmd_wav = ["ffmpeg", "-y", "-i", vag00_clean_wav, wav_05]
            cmd_ogg = ["ffmpeg", "-y", "-i", vag00_clean_wav, "-c:a", "libvorbis", "-q:a", "6", ogg_05]
        else:
            cmd_wav = ["ffmpeg", "-y", "-i", vag00_clean_wav, "-af", f"asetrate={rate_spu},aresample=22050", wav_05]
            cmd_ogg = ["ffmpeg", "-y", "-i", vag00_clean_wav, "-af", f"asetrate={rate_spu},aresample=22050", "-c:a", "libvorbis", "-q:a", "6", ogg_05]

        subprocess.run(cmd_wav, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(cmd_ogg, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Также создаём копию с техническим именем в папке 05
        name_en = spec["name_en"]
        shutil.copy2(wav_05, os.path.join(OUT_DIR_05, f"{name_en}_clean.wav"))
        shutil.copy2(ogg_05, os.path.join(OUT_DIR_05, f"{name_en}_clean.ogg"))

        # Обновляем game/audio/
        for alias in spec["aliases_game"]:
            dst_wav = os.path.join(OUT_DIR_GAME, f"{alias}.wav")
            dst_ogg = os.path.join(OUT_DIR_GAME, f"{alias}.ogg")
            shutil.copy2(wav_05, dst_wav)
            shutil.copy2(ogg_05, dst_ogg)
            print(f"  -> Обновлён game/audio/{alias}.[wav,ogg]")

        # Обновляем SLOT_AUDIO/ если алиас там используется
        for alias in spec["aliases_game"]:
            dst_wav = os.path.join(OUT_DIR_SLOT, f"{alias}.wav")
            dst_ogg = os.path.join(OUT_DIR_SLOT, f"{alias}.ogg")
            if os.path.exists(dst_wav) or os.path.exists(dst_ogg) or alias in ["sfx_00_vag00_n60", "sfx_07_spin_vag00_n67", "sfx_05_victory_vag00_n65", "sfx_06_fail_vag00_n66"]:
                shutil.copy2(wav_05, dst_wav)
                shutil.copy2(ogg_05, dst_ogg)
                print(f"  -> Обновлён SLOT_AUDIO/{alias}.[wav,ogg]")

    print("\nГенерация завершена успешно!")


if __name__ == "__main__":
    generate_clean_audio()
