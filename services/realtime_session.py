class VoiceSession:

    def __init__(self):

        self.audio_buffer = bytearray()

        self.last_voice_time = 0

        self.device_id = ""