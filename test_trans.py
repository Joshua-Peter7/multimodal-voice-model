import asyncio
from src.translation.llm_translator import LLMTranslator
from src.config_loader import cfg

async def test_trans():
    translator = LLMTranslator()
    res = await translator.translate("This is a test of the speech recognition system and real-time translation.", cfg.enabled_languages)
    print("Translations:", res.translations)
    await translator.close()

asyncio.run(test_trans())
