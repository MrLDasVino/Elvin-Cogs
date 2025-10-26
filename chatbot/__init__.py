from .chatbot import ChatBot

async def setup(bot):
    await bot.add_cog(ChatBot(bot))
