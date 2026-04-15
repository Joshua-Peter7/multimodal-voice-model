import sys

with open('src/stt/soniox_client.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Fix 1: Update config in _connect
config_old = '''        config = {
            "api_key": self._cfg.api_key,
            "model": self._cfg.model,
            "sample_rate": self._cfg.sample_rate,
            "num_audio_channels": self._cfg.num_audio_channels,
            "include_nonfinal": self._cfg.include_nonfinal,
            "max_alternatives": self._cfg.max_alternatives,
        }'''
config_new = '''        config = {
            "api_key": self._cfg.api_key,
            "model": self._cfg.model,
            "audio_format": "s16le",
            "sample_rate": self._cfg.sample_rate,
            "num_audio_channels": self._cfg.num_audio_channels,
            "include_nonfinal": self._cfg.include_nonfinal,
        }'''

if config_old in code:
    code = code.replace(config_old, config_new)
else:
    print("Warning: config block not found")

# Fix 2: Update EOF message
eof_old = 'await ws.send_str(json.dumps({"eof": True}))'
eof_new = 'await ws.send_str(json.dumps({"type": "finalize"}))'

if eof_old in code:
    code = code.replace(eof_old, eof_new)
else:
    print("Warning: eof block not found")

with open('src/stt/soniox_client.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Updated soniox_client.py")
