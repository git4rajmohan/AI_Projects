# Standalone transcription runner (spawned as a subprocess by podcast_ui.py).
# faster-whisper's ctranslate2 thread pool deadlocks inside the uvicorn app
# process when the Proactor loop owns the main thread; running here in a
# clean python.exe avoids it entirely.
import sys
import json

import lesson6_podcast_agent as engine


def main() -> None:
    audio_path, model_name = sys.argv[1], sys.argv[2]

    def cb(pct, msg):
        print(json.dumps({"p": pct, "m": msg}), flush=True)

    result = engine.transcribe_audio_file(audio_path, model_name=model_name,
                                          progress_cb=cb)
    print(json.dumps({"final": True, "result": result}), flush=True)


if __name__ == "__main__":
    main()