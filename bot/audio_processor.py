from pydub import AudioSegment
from pydub.effects import low_pass_filter

class AudioProcessor:
    @staticmethod
    def apply_slow(audio: AudioSegment, speed: float) -> AudioSegment:
        """Замедление/ускорение аудио"""
        return audio._spawn(
            audio.raw_data,
            overrides={"frame_rate": int(audio.frame_rate * speed)}
        ).set_frame_rate(audio.frame_rate)

    @staticmethod
    def apply_reverb(audio: AudioSegment, delay: int, decay: float) -> AudioSegment:
        """Добавление реверберации"""
        delayed = audio[-delay:].append(
            AudioSegment.silent(duration=delay),
            crossfade=0
        ).apply_gain(decay * 20)
        return audio.overlay(delayed, times=2, position=delay//2)

    @staticmethod
    def adjust_bass(audio: AudioSegment, gain_db: float) -> AudioSegment:
        """Коррекция низких частот"""
        if gain_db < 0:
            return low_pass_filter(audio, cutoff=200).apply_gain(gain_db)
        elif gain_db > 0:
            return audio.low_pass_filter(150).apply_gain(gain_db) + audio
        return audio