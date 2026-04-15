import re

with open('src/pipeline/orchestrator.py', 'r', encoding='utf-8') as f:
    code = f.read()

pattern = r'    async def _translate_and_stream\(.*?self\._stats\.total_latency_ms \+= total_latency'

replacement = '''    async def _translate_and_stream(
        self, text: str, ctx: UtteranceContext, is_final: bool
    ) -> None:
        """
        Core pipeline: text -> Groq Streaming Translation -> ElevenLabs Streaming TTS -> Broadcast.
        """
        pipeline_start = time.perf_counter()

        async def _process_language(lang):
            try:
                token_stream = self._translator.translate_stream_language(text, lang)
                
                chunk_counter = 0
                async for chunk in self._tts.stream_one_ws(token_stream, lang):
                    if chunk.is_final or not chunk.audio_chunk:
                        continue
                        
                    latency = (time.perf_counter() - pipeline_start) * 1000
                    if chunk_counter == 0:
                        self._stats.tts_first_chunk_ms = latency
                        
                    await self._channels.publish_audio_chunk(
                        lang_code=chunk.lang_code,
                        audio_chunk=chunk.audio_chunk,
                        chunk_index=chunk_counter,
                        source_text=text,
                        translated_text="",
                        is_final=is_final,
                        pipeline_latency_ms=latency,
                        moderation_flag=False,
                    )
                    chunk_counter += 1
            except Exception as e:
                log.error("language_pipeline_error", lang=lang.code, error=str(e))

        target_langs = cfg.enabled_languages
        if target_langs:
            tasks = [_process_language(lang) for lang in target_langs]
            await asyncio.gather(*tasks)

        if is_final:
            total_latency = (time.perf_counter() - pipeline_start) * 1000
            self._stats.total_utterances += 1
            self._stats.total_latency_ms += total_latency'''

new_code = re.sub(pattern, replacement, code, flags=re.DOTALL)
with open('src/pipeline/orchestrator.py', 'w', encoding='utf-8') as f:
    f.write(new_code)
print('Done!')
