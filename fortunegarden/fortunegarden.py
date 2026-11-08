import random
import logging
from datetime import datetime, timedelta

import discord
from discord.ext import tasks
from redbot.core import commands, Config, bank

log = logging.getLogger(__name__)

DEFAULT_DISCOVER_MSG = (
    "{mention} 🌱 You discovered a fortune seed! "
    "You now have **{seeds}** seed{plural}.  \n"
    "Use `{prefix}plantfortune` to plant one!"
)

SEED_BANNER = "https://files.catbox.moe/eayj32.png"
PLANT_BANNER = "https://files.catbox.moe/wvf27j.png"
LIST_BANNER = "https://files.catbox.moe/rn4git.png"
REWARD_BANNERS = {
    "currency": "https://files.catbox.moe/qc1h6u.png",
    "prompt":   "https://files.catbox.moe/q04tqy.png",
    "fortune":  "https://files.catbox.moe/4jbpxq.png",
    "advice":   "https://files.catbox.moe/1gs6jr.png",
}

PROMPTS = [
    "Write a letter to your future self.",
    "Describe a world where trees glow at night.",
    "Create a 50-word mystery scene.",
    "Invent a new holiday and its traditions.",
    "Sketch a dialogue between a human and an AI.",
    "Write a scene where a character wakes up in a desert with no memory of how they arrived.",
    "Describe a floating island nation and its unique customs.",
    "Imagine a future where plants communicate through color changes.",
    "Write a dialogue between two rival time travelers negotiating a peace treaty.",
    "Craft a letter from a soldier on an alien planet to their family on Earth.",
    "Describe a city built entirely from glass and its hidden dangers.",
    "Invent a holiday celebrated by robots and its unusual traditions.",
    "Write a diary entry of someone living under the ocean.",
    "Sketch a marketplace where people trade memories instead of goods.",
    "Create a 100-word mystery that begins with a missing shoe.",
    "Write a recipe for happiness using metaphorical ingredients.",
    "Describe a world where everyone has a visible countdown timer above their heads.",
    "Imagine a conversation between a ghost and a living relative.",
    "Write a scene set in a train that never stops moving.",
    "Invent a sport played by aerial creatures in the sky.",
    "Craft a bedtime story told by an artificial intelligence to children.",
    "Describe a library that contains every book ever thought of but none ever published.",
    "Write a short biography of a mythical creature that lives in city sewers.",
    "Imagine a world where colors taste like different fruits.",
    "Create a dialogue between a mirror and the person looking into it.",
    "Write a flash fiction piece from the perspective of a raindrop falling on a rooftop.",
    "Describe a garden that grows memories instead of plants.",
    "Invent a device that translates emotions into music and its inventor's regrets.",
    "Write a postcard from a tourist visiting the Moon.",
    "Sketch a conversation between two stars witnessing Earth's history.",
    "Write a scene where a day lasts only five minutes.",
    "Explain a ritual that summons the wind and its consequences.",
    "Create a poem about the silence between two heartbeats.",
    "Describe a city at the bottom of a crystal-clear lake.",
    "Write a story that starts at the end and works backwards.",
    "Imagine a library where books rewrite themselves based on readers' thoughts.",
    "Craft a dialogue between a human and their future self.",
    "Describe the taste of memories long forgotten.",
    "Write a scene in which shadows come to life at night.",
    "Invent a game where players bet on the outcome of dreams.",
    "Write a letter from a child to their future self 50 years ahead.",
    "Describe the interior of a clock that counts lives instead of time.",
    "Create a 200-word flashback that reveals a character's secret.",
    "Sketch an ecosystem on a planet with no sunlight.",
    "Imagine a world where everyone must tell a lie once a day.",
    "Write a conversation between two abandoned robots.",
    "Describe an island that changes shape daily.",
    "Invent a perfume that evokes forgotten memories.",
    "Write a scene set in a café at the edge of a black hole.",
    "Craft a story that spans a single breath.",
    "Describe the sound of colors clashing in the sky.",
    "Imagine a society where poetry is currency.",
    "Write a flash fiction about a disappearing village.",
    "Sketch an argument between morning and night.",
    "Create a dialogue between a dream and reality.",
    "Write a letter from a tree to the person who planted it.",
    "Describe a festival that celebrates the end of the world.",
    "Invent a sport that uses gravity as a playing field.",
    "Write a 60-word horror scene in an abandoned hospital.",
    "Imagine a world where music controls the weather.",
    "Craft a scene where gravity suddenly reverses in a city.",
    "Describe a mentor who teaches magic through cooking.",
    "Write a conversation between a statue and the sculptor's descendant.",
    "Invent a language spoken only by birds.",
    "Sketch a journey across a desert made of glass.",
    "Create a monologue from a lighthouse keeper on Mars.",
    "Describe a mask that reveals someone's true self.",
    "Write a flash fiction about a book that writes its own ending.",
    "Imagine a world where noses detect emotions.",
    "Craft a letter from an explorer descending into Earth's core.",
    "Describe a carnival where every ride tells a story.",
    "Write a scene where televisions predict your future.",
    "Invent a potion that lets you speak to the dead and its side effects.",
    "Sketch the life of a clockmaker who controls time.",
    "Create a dialogue between a rainstorm and the clouds.",
    "Write a 150-word scene set in a city without gravity.",
    "Describe a world where echoes have memories.",
    "Imagine a creature born from the stars and its first steps on Earth.",
    "Craft a story that unfolds through newspaper headlines.",
    "Describe a painting that changes every time you look away.",
    "Write a poem about the smell of midnight.",
    "Invent a device that captures dreams and sells them.",
    "Sketch a world where books grow on trees.",
    "Write a letter from a future AI to its creator.",
    "Describe the taste of the first snowfall.",
    "Create a dialogue between fire and ice.",
    "Write a scene where all water vanishes for a day.",
    "Imagine a city built on the backs of giant turtles.",
    "Craft a flash fiction about the last breath of a dying star.",
    "Describe a mirror that shows alternate realities.",
    "Write a monologue from a ghost who haunts libraries.",
    "Invent a holiday celebrating a myth you've created.",
    "Sketch a society governed by poets instead of politicians.",
    "Write a 100-word mystery about a locked room.",
    "Describe a symphony performed by the ocean waves.",
    "Imagine a world where seasons have personalities.",
    "Craft a dialogue between a labyrinth and its wanderer.",
    "Describe the life cycle of a thought.",
    "Write a flash fiction set in an eternal night.",
    "Invent a creature that feeds on human stories.",
    "Sketch a desert where the sand sings songs.",
    "Write a letter from a citizen of a world with no shadows.",
    "Describe a machine that builds towers to the sky.",
    "Imagine a festival where people swap identities for a day.",
    "Craft a scene where gravity is optional.",
    "Write a diary entry from a dragon observing a bustling human city.",
    "Describe a marketplace where dreams are bought and sold.",
    "Invent a ritual for greeting the sun and its symbolic meaning.",
    "Create a conversation between two statues in a deserted park.",
    "Write a scene where gravity flickers on and off randomly.",
    "Sketch a world where shadows have personalities and walk away.",
    "Describe a library that organizes books by emotions.",
    "Imagine a festival celebrating the migration of whales across the sky.",
    "Write a letter from a time traveler stuck in the wrong era.",
    "Describe a potion that changes memories into visible holograms.",
    "Invent a sport played underwater by merfolk.",
    "Write a backstage diary of a puppet told by the puppet.",
    "Create a 75-word scene set in an elevator that never reaches the top.",
    "Describe a dimension where colors are sounds and sounds are colors.",
    "Write a conversation between a river and the clouds.",
    "Imagine a city built inside a volcano and its daily life.",
    "Sketch a portrait of a person through the eyes of a painting.",
    "Write a flash fiction about a letter that writes back.",
    "Describe the taste of the wind on different days.",
    "Invent a holiday celebrating forgotten songs.",
    "Create a dialogue between a starship AI and a sentient star.",
    "Write a monologue from an abandoned amusement park ride.",
    "Describe a dream where you meet your earliest self.",
    "Imagine a world where everyone carries a personal soundtrack.",
    "Write a scene at a restaurant for mythical creatures.",
    "Invent a machine that weaves stories into cloth.",
    "Sketch a tale told by a pebble at the bottom of a well.",
    "Describe a garden where statues bloom like flowers.",
    "Write a letter from someone who lives on a cloud.",
    "Create a mystery with only one clue: a broken mirror shard.",
    "Imagine a society where words appear visually in the air.",
    "Write a 120-word flashback of the last human on Mars.",
    "Describe a library whose books whisper secrets.",
    "Invent a board game that decides fates.",
    "Sketch a world where time flows backwards at night.",
    "Write about a musician whose instrument controls nature.",
    "Describe a mask that grants its wearer another identity.",
    "Imagine an island made entirely of glass and its perils.",
    "Create a dialogue between two constellations.",
    "Write a scene where letters fall from the sky like rain.",
    "Describe a city where buildings rearrange themselves daily.",
    "Invent a device that records your dreams to play back.",
    "Write a poem about the space between two raindrops.",
    "Sketch a chase scene through a maze of mirrors.",
    "Describe a library that lends out emotions instead of books.",
    "Write a conversation between a comet and a planet.",
    "Imagine a carnival that appears only at midnight.",
    "Create a mystery set in a silent music hall.",
    "Describe a potion that lets you taste the past.",
    "Write a story told entirely through diary entries of an AI.",
    "Sketch a day in the life of a ghost tour guide.",
    "Invent a language based on dance movements.",
    "Describe a world where dreams and reality merge at dawn.",
    "Write a scene in a theater where the audience is the show.",
    "Imagine a city where everyone lives on rooftops.",
    "Create a dialogue between a lighthouse and the sea.",
    "Write a flash fiction about a book that fades as you read.",
    "Describe a festival celebrating the last leaf of autumn.",
    "Invent a graffiti that comes to life at night.",
    "Sketch a conversation between a painter and their painting.",
    "Write a monologue from a key lost in a forest.",
    "Describe a spaceship’s log entry from a one-way mission.",
    "Imagine a market where emotions are barter items.",
    "Create an 80-word flashback in a desert temple.",
    "Write a letter from the moon to the sun.",
    "Sketch a world where seasons have wardrobes.",
    "Describe a rainstorm made of light.",
    "Invent a creature that farms stardust.",
    "Write a scene where people communicate through colors.",
    "Imagine a game played on the rings of Saturn.",
    "Create a dialogue between a tree and its own reflection.",
    "Write a mystery that unfolds through postcards.",
    "Describe a banquet attended by legendary heroes.",
    "Invent a device that translates animal thoughts.",
    "Sketch a journey through a tunnel of echoes.",
    "Write a letter from an explorer on an ocean of glass.",
    "Describe a city where inhabitants switch bodies weekly.",
    "Imagine a library hidden beneath a waterfall.",
    "Create a poem about footprints in the sand that vanish.",
    "Write a scene set in a train station that spans dimensions.",
    "Describe a mirror that shows future selves.",
    "Invent a festival where people share smells instead of stories.",
    "Sketch a conversation between two memories.",
    "Write a flash fiction about a star that fell in love.",
    "Describe an island that sings ancient songs.",
    "Imagine a ship that sails on desert dunes.",
    "Create a dialogue between a dream and a nightmare.",
    "Write a letter to someone who never existed.",
    "Describe a candle that burns memories instead of wax.",
    "Invent a sport where players ride lightning bolts.",
    "Sketch a chase inside a collapsing library.",
    "Write a scene where you meet the person you’ll become.",
    "Describe a festival celebrating the birth of rivers.",
    "Imagine a world where laughter is visible as color.",
    "Create a mystery about a disappearing river.",
    "Write a poem about the echo of a song long forgotten.",
    "Describe a machine that builds bridges between thoughts.",
    "Invent a city that rearranges itself based on dreams.",
    "Sketch a day in the life of a cloud painter.",
    "Write a story that begins at sunrise and ends at sunset."    
]
    
FORTUNES = [
    "A pleasant surprise is around the corner.",
    "Change begins at the end of your comfort zone.",
    "Someone you least expect will bring joy today.",
    "Great achievements start with small steps.",
    "Your persistence will soon pay off.",
    "A pleasant surprise is waiting for you.",
    "Your hard work will soon pay off in unexpected ways.",
    "New opportunities are on the horizon.",
    "An old acquaintance will re-enter your life.",
    "Kindness shown to others will return to you.",
    "A fresh start will become available to you.",
    "Your creativity will lead to real success.",
    "Trust your instincts; they will guide you well.",
    "A small act of generosity will create a ripple effect.",
    "Happiness begins with a single step forward.",
    "Your positive attitude will attract good fortune.",
    "A chance encounter will change your outlook.",
    "Patience will reward you in due time.",
    "You are about to embark on a new adventure.",
    "A meaningful friendship is just around the corner.",
    "Your smile will brighten someone's day.",
    "Courage will open doors you never imagined.",
    "An opportunity to learn will present itself.",
    "Balance in life will bring you peace.",
    "A financial blessing is heading your way.",
    "Your persistence will overcome current challenges.",
    "New knowledge will empower your choices.",
    "A heartfelt conversation will strengthen a bond.",
    "Joy will find you when you least expect it.",
    "You will discover a hidden talent.",
    "An exciting journey is on your path.",
    "Your compassion will make a difference.",
    "A fresh perspective will solve an old problem.",
    "Serendipity will lead you to something wonderful.",
    "Your generosity will be remembered.",
    "An inspiring idea will spark creativity.",
    "Good news will arrive in the mail.",
    "You will overcome a lingering worry.",
    "A new friendship will enrich your life.",
    "Your kindness will open unexpected doors.",
    "An adventure in nature will rejuvenate you.",
    "Your wit will delight those around you.",
    "A small risk will bring big rewards.",
    "You will find clarity in a confusing situation.",
    "A moment of stillness will bring insight.",
    "Your optimism will lead to success.",
    "A creative project will receive praise.",
    "You will achieve a long-sought goal.",
    "A timely reminder will guide your decisions.",
    "Your efforts will inspire others.",
    "A surprise gift will brighten your day.",
    "You will experience a wave of inspiration.",
    "An unexpected call will bring good news.",
    "Your dedication will be recognized.",
    "You will make someone’s day with your words.",
    "A warm connection will deepen soon.",
    "You will learn something valuable today.",
    "An upcoming event will bring joy.",
    "Your sincerity will earn trust.",
    "A new chapter begins with a single page.",
    "Your laughter will be contagious.",
    "You will find beauty in simplicity.",
    "A moment of courage will change everything.",
    "Your dreams are closer than they appear.",
    "An act of kindness will find its way back.",
    "You will receive an unexpected compliment.",
    "Your insights will help someone in need.",
    "A flash of inspiration will guide your path.",
    "You will make a breakthrough soon.",
    "A joyful surprise awaits you at home.",
    "Your generosity will sow seeds of happiness.",
    "An overdue recognition is on the way.",
    "You will embrace a new beginning.",
    "A simple change will bring great joy.",
    "You will find harmony in all you do.",
    "A new friendship will blossom quickly.",
    "Your efforts will lead to a surprising outcome.",
    "A peaceful moment will restore your spirit.",
    "Your next idea will be your best yet.",
    "An opportunity to travel will present itself.",
    "You will conquer a fear soon.",
    "A comforting message will arrive unexpectedly.",
    "Your talents will be celebrated.",
    "A new hobby will bring you delight.",
    "You will find balance in unexpected ways.",
    "An inspiring person will cross your path.",
    "Your words will have a positive impact.",
    "A new perspective will invigorate you.",
    "Your resilience will see you through.",
    "A long-awaited decision will go your way.",
    "Your kindness will light up the room.",
    "A small discovery will spark excitement.",
    "Your patience will lead to a big win.",
    "A cherished memory will bring you comfort.",
    "Your next step will feel like destiny.",
    "A supportive friend will appear just when needed.",
    "Your heart will guide you to happiness.",
    "A chance for growth is heading your way.",
    "Your spirit will shine bright today.",
    "A fortunate coincidence will delight you.",
    "Your inner strength will be your ally.",
    "A new goal will inspire you.",
    "Your journey will take a positive turn.",
    "A small victory will boost your confidence.",
    "Your optimism will attract wonderful surprises.",
    "A heartfelt compliment will come your way soon.",
    "You will find joy in an unexpected place.",
    "A new skill will open a door for you.",
    "Your generosity will inspire someone today.",
    "Adventure awaits if you step outside your comfort zone.",
    "You will uncover a surprising truth.",
    "A small habit change will yield big results.",
    "Someone’s act of kindness will brighten your day.",
    "You will solve a problem you’ve been avoiding.",
    "A creative spark will lead to a breakthrough.",
    "Your positive energy will be contagious.",
    "An old dream will rekindle your passion.",
    "You will meet someone who shares your vision.",
    "A quiet moment will bring you clarity.",
    "Trust will grow in an important relationship.",
    "You will discover strength you didn’t know you had.",
    "A spontaneous decision will lead to fun.",
    "You will achieve more than you expect today.",
    "Your insight will help someone in need.",
    "A piece of advice will change your perspective.",
    "You will accomplish a task faster than planned.",
    "A surprise gift will arrive just when you need it.",
    "Your hard work will be publicly acknowledged.",
    "You will make a decision that feels like destiny.",
    "A fresh idea will energize your next project.",
    "You will find balance between work and play.",
    "A simple gesture will deepen a friendship.",
    "You will gain respect through your honesty.",
    "A moment of patience will pay off richly.",
    "Your kindness will return to you tenfold.",
    "You will unlock a hidden talent today.",
    "An important message arrives when you least expect it.",
    "You will find peace in a busy day.",
    "A challenge will strengthen your resolve.",
    "You will inspire someone without realizing it.",
    "A new book will give you valuable insight.",
    "You will create something truly memorable.",
    "A kind word will have a lasting impact.",
    "You will reconnect with someone meaningful.",
    "A healthful habit will transform your routine.",
    "Your laughter will lift someone’s spirits.",
    "You will receive support when you ask for it.",
    "A chance opportunity will advance your goals.",
    "Your instincts will guide you to success.",
    "You will experience a moment of pure joy.",
    "A thoughtful gesture will bridge a gap.",
    "You will find clarity in a complex situation.",
    "A new perspective will emerge from a conversation.",
    "Your efforts will ripple outward positively.",
    "You will be pleasantly surprised by progress.",
    "A secret talent will reveal itself to you.",
    "You will find comfort in a cherished memory.",
    "A small victory will boost your confidence.",
    "You will create a lasting memory today.",
    "A difficult decision will become clear.",
    "You will receive encouragement from an ally.",
    "A fresh start will feel exhilarating.",
    "You will accomplish a goal you set aside.",
    "A reassuring word will ease your mind.",
    "You will discover unexpected resources.",
    "A long-term project will reach a milestone.",
    "You will find inspiration in the everyday.",
    "A positive change is on the horizon.",
    "You will be recognized for your efforts.",
    "A moment of silence will bring inner peace.",
    "You will take the lead when needed.",
    "A new connection will enrich your network.",
    "You will find beauty in simplicity.",
    "A timely suggestion will prove invaluable.",
    "You will experience meaningful growth today.",
    "A small risk will lead to great reward.",
    "You will learn something that changes your path.",
    "A moment of generosity will be remembered.",
    "You will gain clarity through reflection.",
    "A creative collaboration will spark magic.",
    "You will find joy in helping others.",
    "A simple change will lift your spirits.",
    "You will navigate a challenge with grace.",
    "A supportive friend will reach out soon.",
    "You will make meaningful progress today.",
    "A fresh idea will invigorate your mind.",
    "You will discover a path you hadn’t seen.",
    "A moment of courage will bring success.",
    "You will find peace in an unexpected moment.",
    "A kind gesture will warm your heart.",
    "You will accomplish more than you imagined.",
    "A joyful reunion is coming your way.",
    "You will receive good news via message.",
    "A moment of reflection will guide you forward.",
    "You will shine in a team effort today.",
    "A new opportunity will present itself soon."        
]
    
ADVICE = [
    "Remember to take breaks and breathe deeply.",
    "A clear mind makes better decisions.",
    "Collaboration often sparks the best ideas.",
    "Small daily habits lead to big results.",
    "Listen more than you speak.",
    "Take a moment each day to breathe deeply and center yourself.",
    "Focus on progress rather than perfection.",
    "Listen more than you speak to truly understand others.",
    "Set clear boundaries to protect your energy.",
    "Embrace mistakes as opportunities to learn.",
    "Prioritize tasks that align with your core values.",
    "Practice gratitude to shift your mindset to abundance.",
    "Break big goals into small, manageable steps.",
    "Be patient with yourself during challenging times.",
    "Celebrate even the smallest victories.",
    "Stay curious and ask questions freely.",
    "Trust your intuition when making decisions.",
    "Allocate time for rest to avoid burnout.",
    "Make time for activities that spark joy.",
    "Respect your own pace; progress is personal.",
    "Be honest with yourself about your needs.",
    "Surround yourself with supportive people.",
    "Express appreciation to those who help you.",
    "Reflect on your wins at the end of each week.",
    "Let go of what you cannot control.",
    "Practice empathy to build stronger connections.",
    "Keep learning something new every day.",
    "Take regular breaks to recharge your focus.",
    "Speak kindly to yourself; self-talk matters.",
    "Document your thoughts in a journal for clarity.",
    "Set realistic deadlines to maintain momentum.",
    "Protect your mental space from negative influences.",
    "Invest time in hobbies that inspire you.",
    "Ask for help when the task is too big.",
    "Maintain a consistent sleep schedule for well-being.",
    "Use setbacks as fuel for future success.",
    "Plan ahead but remain flexible to change.",
    "Practice one act of kindness each day.",
    "Challenge yourself to step outside your comfort zone.",
    "Limit multitasking to improve concentration.",
    "Stand up for your beliefs with confidence.",
    "Prioritize tasks based on impact, not urgency.",
    "Make time for self-reflection regularly.",
    "Keep a positive outlook in the face of adversity.",
    "Trust that you have the resources to adapt.",
    "Learn to say no without guilt.",
    "Maintain curiosity about the world around you.",
    "Practice mindful eating to nourish your body.",
    "Declutter your environment to clear your mind.",
    "Stay focused on what you can influence.",
    "Visualize success to motivate your actions.",
    "Review your goals every month for accountability.",
    "Share your successes to inspire others.",
    "Take responsibility for your happiness.",
    "Embrace change as a pathway to growth.",
    "Guard your time like your most valuable asset.",
    "Seek feedback to improve continuously.",
    "Balance work with play to sustain creativity.",
    "Cultivate resilience through daily challenges.",
    "Spend time in nature to restore balance.",
    "Keep your promises to build trust.",
    "Start each day with a clear intention.",
    "Invest in relationships that uplift you.",
    "Face fears one small step at a time.",
    "Reflect on lessons learned during setbacks.",
    "Practice active listening in every conversation.",
    "Be open to adapting your goals as needed.",
    "Express gratitude to yourself for your efforts.",
    "Seek out mentors to guide your journey.",
    "Take responsibility instead of placing blame.",
    "Embrace simplicity to reduce stress.",
    "Set boundaries on social media use.",
    "Nurture your creativity with daily practice.",
    "Focus on solutions rather than dwelling on problems.",
    "Celebrate others' successes as well as your own.",
    "Make a habit of reviewing your finances.",
    "Find comfort in routine during chaotic times.",
    "Approach challenges with a beginner's mindset.",
    "Let go of perfectionism to finish tasks sooner.",
    "Stay open to constructive criticism.",
    "Plan times for reflection and adjustment.",
    "Practice self-compassion in moments of doubt.",
    "Surprise yourself by trying something new.",
    "Listen to your body’s cues for rest or action.",
    "Build habits that reinforce your long-term vision.",
    "Express your creativity in multiple forms.",
    "Set aside time for meaningful conversations.",
    "Trust that consistency cultivates change.",
    "Document your achievements to boost confidence.",
    "Allow yourself to pause and recalibrate.",
    "Keep your workspace organized to boost productivity.",
    "Use affirmations to reinforce positive beliefs.",
    "Seek balance between giving and receiving.",
    "Invest in skills that align with your purpose.",
    "Remind yourself daily of your core strengths.",
    "Maintain integrity even when no one is watching.",
    "Cultivate a mindset of lifelong learning.",
    "Check in with friends and family regularly.",
    "Use challenges to refine your strategies.",
    "Stay adaptable in an ever-changing world.",
    "Practice deep listening before responding.",
    "Value progress over immediate perfection.",
    "Take mindful pauses before making big choices.",
    "Keep a learner’s curiosity in every situation.",
    "Remind yourself that every day is a fresh start.",
    "Set micro-goals to build momentum.",
    "Begin each morning with a brief meditation.",
    "Use the two-minute rule for quick tasks.",
    "Batch similar tasks to conserve mental energy.",
    "Keep a brain-dump notebook within reach.",
    "Schedule buffer time between appointments.",
    "Reflect on your achievements at week’s end.",
    "Practice gratitude journaling every evening.",
    "Delegate tasks that don’t require your focus.",
    "Turn off non-essential notifications.",
    "Use a timer to maintain deep focus.",
    "Take a short walk after long screen sessions.",
    "Plan your meals to reduce decision fatigue.",
    "Learn to say no to protect your priorities.",
    "Read something inspiring each day.",
    "Stay hydrated to keep your mind clear.",
    "Tackle your hardest task first each morning.",
    "Pause for three deep breaths when you feel stuck.",
    "Block off “no meeting” time in your calendar.",
    "Create a playlist that uplifts your mood.",
    "Tidy your workspace at the end of each day.",
    "Review tomorrow’s plan before lights-out.",
    "Visualize success for five minutes each morning.",
    "Stand and stretch every hour on the hour.",
    "Unplug from screens an hour before bedtime.",
    "Use positive affirmations to set your mindset.",
    "Record one win in a journal before you sleep.",
    "Keep a running idea list for future projects.",
    "Practice active listening in every conversation.",
    "Turn setbacks into stepping stones for growth.",
    "Set and honor clear personal deadlines.",
    "Reward progress, not just final outcomes.",
    "Spend time outdoors to recharge your spirit.",
    "Display your long-term goals where you’ll see them.",
    "Break large projects into weekly milestones.",
    "Say “thank you” to someone each day.",
    "Cultivate curiosity by asking “why?” often.",
    "Try a new hobby to refresh your mind.",
    "Design a morning routine that energizes you.",
    "End each day with a moment of reflection.",
    "Write down one thing you’re proud of daily.",
    "Check in with your monthly goals regularly.",
    "Streamline routines with simple checklists.",
    "Use color-coded notes to highlight priorities.",
    "Limit multitasking to stay fully present.",
    "Perform a small act of kindness each day.",
    "Join a community for mutual inspiration.",
    "Reserve time for creative, unstructured play.",
    "Capture quick thoughts with voice memos.",
    "Arrange your desk to inspire better focus.",
    "Move around when you need a mental reset.",
    "Set aside a weekly reading hour.",
    "Disable auto-play on video platforms.",
    "Block regular breaks in your daily plan.",
    "Choose analog tools to give your eyes a rest.",
    "Clear one email at a time to avoid overwhelm.",
    "Write thank-you notes to express your gratitude.",
    "Use reminders for your self-care appointments.",
    "Practice guided imagery to calm your mind.",
    "Plan your upcoming week each Sunday evening.",
    "Breathe mindfully before making big decisions.",
    "Keep commitments small to ensure completion.",
    "Track new habits to reinforce consistency.",
    "Reflect on feedback to fuel your professional growth.",
    "Meditate on your goals at least once a week.",
    "Collect inspiring quotes in a dedicated journal.",
    "Adopt a minimalist approach to your tasks.",
    "Set time limits to avoid perfectionism traps.",
    "Sip tea mindfully and appreciate the moment.",
    "Find a mentor to guide your journey.",
    "Listen to a podcast that expands your thinking.",
    "Spend one day away from your phone monthly.",
    "Map out ideas with a simple mind-map.",
    "Balance productivity with restorative rest.",
    "Schedule “thinking time” for big-picture ideas.",
    "Take creative breaks by sketching or doodling.",
    "Practice empathy by imagining others’ perspectives.",
    "Leave work signals behind after office hours.",
    "Save inspiring images in a mood-board folder.",
    "Color-code your calendar for visual clarity.",
    "Find joy in the small routines of your day.",
    "Write a weekly summary of lessons learned.",
    "Ask open-ended questions to spark conversation.",
    "Create a vision board to anchor your goals.",
    "Offer your time generously to others.",
    "Stick sticky notes where reminders are most useful.",
    "Reflect on your energy levels each afternoon.",
    "Try cold showers to boost alertness.",
    "Organize digital files to reduce clutter stress.",
    "Prioritize tasks by their long-term impact.",
    "Learn one new skill every month.",
    "Use positive self-talk during challenging moments.",
    "Notice what activities energize you most.",
    "Reserve five minutes for end-of-day reflection.",
    "Partner with a friend for accountability check-ins.",
    "Practice mindful eating during every meal.",
    "Block deep-work sessions in your schedule.",
    "Keep a success log to celebrate daily wins.",
    "Detach from outcomes to reduce performance anxiety."        
]
    
import asyncio
import logging
import math
import random
import re
import string
from datetime import datetime, timedelta

import discord
from discord.ext import tasks
from redbot.core import Config, bank, commands

log = logging.getLogger(__name__)

MIN_CREDITS = 100
MAX_CREDITS = 300
DEFAULT_REWARD_WEIGHTS = {
    "currency": 28,
    "prompt": 12,
    "fortune": 12,
    "advice": 12,
    "flower": 14,
    "mystery": 8,
    "seed": 6,
    "xp": 6,
    "jackpot": 2,
}
SEED_TYPES = {
    "common": {"label": "Common Seed", "emoji": "🌱", "weight": 70},
    "golden": {"label": "Golden Seed", "emoji": "🌟", "weight": 20},
    "moonlight": {"label": "Moonlight Seed", "emoji": "🌙", "weight": 8},
    "ancient": {"label": "Ancient Seed", "emoji": "🌳", "weight": 2},
}
FLOWERS = {
    "Dandelion": "Common",
    "Clover": "Common",
    "Daisy": "Common",
    "Bluebell": "Common",
    "Moonflower": "Uncommon",
    "Foxglove": "Uncommon",
    "Lavender": "Uncommon",
    "Crystal Rose": "Rare",
    "Star Lily": "Rare",
    "Firefly Orchid": "Rare",
    "Celestial Lily": "Epic",
    "Aurora Bloom": "Epic",
    "Eternal Blossom": "Legendary",
    "Frostbell": "Seasonal",
    "Sakura": "Seasonal",
    "Sunflare": "Seasonal",
    "Harvest Crown": "Seasonal",
}
SEASONAL_EVENTS = {
    "winter": {"name": "Winter's Frost", "flower": "Frostbell", "emoji": "❄️"},
    "spring": {"name": "Spring Blossom Festival", "flower": "Sakura", "emoji": "🌸"},
    "summer": {"name": "Midsummer Night", "flower": "Sunflare", "emoji": "☀️"},
    "autumn": {"name": "Golden Harvest", "flower": "Harvest Crown", "emoji": "🍂"},
}
DECORATION_UNLOCKS = {
    1: "Wildflower Border",
    2: "Butterfly Lanterns",
    3: "Crystal Fountain",
    5: "Moonlit Arch",
    8: "Starfall Pond",
    12: "Celestial Gazebo",
}
ACHIEVEMENT_DESCRIPTIONS = {
    "First Plant": "Plant your first fortune seed.",
    "First Bloom": "Receive your first bloom.",
    "Dedicated Gardener": "Grow 10 seeds.",
    "Master Gardener": "Grow 50 seeds.",
    "Green Thumb": "Reach garden level 5.",
    "Botanist": "Collect 5 different flowers.",
    "Collector's Pride": "Collect 10 different flowers.",
    "Once in a Lifetime": "Discover a legendary flower.",
    "Faithful Waterer": "Reach a seven-day watering streak.",
}


def create_garden(seed_count=0):
    return {
        "seeds": max(0, int(seed_count)),
        "seed_inventory": {"common": max(0, int(seed_count)), "golden": 0, "moonlight": 0, "ancient": 0},
        "flowers": {},
        "garden_xp": 0,
        "garden_level": 1,
        "total_planted": 0,
        "total_blooms": 0,
        "reward_history": [],
        "achievements": [],
        "items": {"fertilizer": 0},
        "applied_reward_ids": [],
        "daily_water_date": None,
        "water_streak": 0,
        "last_water_date": None,
        "event_progress": {},
        "event_claims": [],
        "unlocked_decorations": [],
        "equipped_decoration": None,
    }


def current_seasonal_event(now=None):
    now = now or datetime.utcnow()
    if now.month in (12, 1, 2):
        key = "winter"
    elif now.month in (3, 4, 5):
        key = "spring"
    elif now.month in (6, 7, 8):
        key = "summer"
    else:
        key = "autumn"
    event = dict(SEASONAL_EVENTS[key])
    event["key"] = f"{now.year}-{key}"
    event["season"] = key
    return event


class FortunePaginator(discord.ui.View):
    def __init__(self, author_id, pages):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.pages = pages
        self.index = 0
        self.message = None
        self._refresh_buttons()

    def _refresh_buttons(self):
        self.previous_button.disabled = self.index <= 0
        self.next_button.disabled = self.index >= len(self.pages) - 1

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("These garden pages belong to someone else.", ephemeral=True)
            return False
        return True

    async def _show_page(self, interaction):
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, emoji="◀️")
    async def previous_button(self, interaction, button):
        self.index = max(0, self.index - 1)
        await self._show_page(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji="▶️")
    async def next_button(self, interaction, button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        await self._show_page(interaction)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class FortuneGarden(commands.Cog):
    @commands.command(name="fortunegarden", help="Show the FortuneGarden command list.")
    async def fortunegarden(self, ctx):
        await self.bot.send_help_for(ctx, self)

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210987)
        self.config.register_guild(
            fortunes={},
            min_credits=MIN_CREDITS,
            max_credits=MAX_CREDITS,
            discover_message=None,
            enabled=True,
            seed_chance=5.0,
            seed_cooldown=60,
            seed_limit=20,
            min_bloom_hours=1,
            max_bloom_hours=12,
            reward_weights=DEFAULT_REWARD_WEIGHTS,
            reward_channel=None,
            ignored_channels=[],
            ignored_roles=[],
            min_message_length=8,
            watering_minutes=30,
            fertilizing_minutes=60,
        )
        self.config.register_member(
            seeds=0,
            last_earned=None,
            opt_out=False,
            garden=None,
        )
        self._guild_locks = {}
        self._member_locks = {}

    def cog_load(self):
        if not self.bloom_loop.is_running():
            self.bloom_loop.start()

    def cog_unload(self):
        self.bloom_loop.cancel()

    def _guild_lock(self, guild_id):
        guild_id = int(guild_id)
        if guild_id not in self._guild_locks:
            self._guild_locks[guild_id] = asyncio.Lock()
        return self._guild_locks[guild_id]

    def _member_lock(self, guild_id, user_id):
        key = (int(guild_id), int(user_id))
        if key not in self._member_locks:
            self._member_locks[key] = asyncio.Lock()
        return self._member_locks[key]

    async def _save_garden(self, member_conf, garden):
        inventory = garden.setdefault("seed_inventory", {})
        for seed_type in SEED_TYPES:
            inventory[seed_type] = max(0, int(inventory.get(seed_type, 0)))
        garden["seeds"] = sum(inventory.values())
        garden["garden_xp"] = max(0, int(garden.get("garden_xp", 0)))
        garden["garden_level"] = max(1, int(garden.get("garden_level", 1)))
        await member_conf.garden.set(garden)
        await member_conf.seeds.set(garden["seeds"])

    async def _get_garden(self, member_conf):
        garden = await member_conf.garden()
        if not isinstance(garden, dict):
            legacy_seeds = max(0, int(await member_conf.seeds()))
            garden = create_garden(legacy_seeds)
            await self._save_garden(member_conf, garden)
            return garden

        changed = False
        defaults = create_garden()
        for key, value in defaults.items():
            if key not in garden:
                garden[key] = value
                changed = True
        inventory = garden.get("seed_inventory")
        if not isinstance(inventory, dict):
            inventory = {"common": max(0, int(garden.get("seeds", 0)))}
            garden["seed_inventory"] = inventory
            changed = True
        inventory_total = 0
        for seed_type in SEED_TYPES:
            value = max(0, int(inventory.get(seed_type, 0)))
            if inventory.get(seed_type) != value:
                inventory[seed_type] = value
                changed = True
            inventory_total += value
        stored_total = max(0, int(garden.get("seeds", 0)))
        if inventory_total == 0 and stored_total > 0:
            inventory["common"] = stored_total
            inventory_total = stored_total
            changed = True
        elif inventory_total != stored_total:
            garden["seeds"] = inventory_total
            changed = True
        if changed or int(await member_conf.seeds()) != inventory_total:
            await self._save_garden(member_conf, garden)
        return garden

    def _seed_count(self, garden):
        return sum(max(0, int(value)) for value in garden.get("seed_inventory", {}).values())

    def _add_xp(self, garden, amount):
        garden["garden_xp"] = max(0, int(garden.get("garden_xp", 0)) + int(amount))
        new_level = 1 + garden["garden_xp"] // 100
        old_level = int(garden.get("garden_level", 1))
        garden["garden_level"] = new_level
        unlocked = garden.setdefault("unlocked_decorations", [])
        for level, decoration in DECORATION_UNLOCKS.items():
            if new_level >= level and decoration not in unlocked:
                unlocked.append(decoration)
        return new_level - old_level

    def _check_achievements(self, garden):
        earned = set(garden.get("achievements", []))
        flowers = garden.get("flowers", {})
        unique_flowers = len([name for name, count in flowers.items() if count > 0])
        flower_rarities = {FLOWERS.get(name, "Common") for name, count in flowers.items() if count > 0}
        checks = {
            "First Plant": garden.get("total_planted", 0) >= 1,
            "First Bloom": garden.get("total_blooms", 0) >= 1,
            "Dedicated Gardener": garden.get("total_blooms", 0) >= 10,
            "Master Gardener": garden.get("total_blooms", 0) >= 50,
            "Green Thumb": garden.get("garden_level", 1) >= 5,
            "Botanist": unique_flowers >= 5,
            "Collector's Pride": unique_flowers >= 10,
            "Once in a Lifetime": "Legendary" in flower_rarities,
            "Faithful Waterer": garden.get("water_streak", 0) >= 7,
        }
        newly_earned = []
        for name, condition in checks.items():
            if condition and name not in earned:
                garden.setdefault("achievements", []).append(name)
                newly_earned.append(name)
        return newly_earned

    def _add_flower(self, garden, flower_name):
        flowers = garden.setdefault("flowers", {})
        flowers[flower_name] = max(0, int(flowers.get(flower_name, 0))) + 1

    def _choose_seed_type(self):
        names = list(SEED_TYPES)
        weights = [SEED_TYPES[name]["weight"] for name in names]
        return random.choices(names, weights=weights, k=1)[0]

    def _choose_flower(self, seed_type, event):
        rarity_weights = {
            "common": [60, 25, 11, 3, 1],
            "golden": [45, 27, 18, 7, 3],
            "moonlight": [40, 25, 20, 10, 5],
            "ancient": [30, 25, 25, 14, 6],
        }
        rarities = ["Common", "Uncommon", "Rare", "Epic", "Legendary"]
        weights = rarity_weights.get(seed_type, rarity_weights["common"])
        rarity = random.choices(rarities, weights=weights, k=1)[0]
        candidates = [name for name, flower_rarity in FLOWERS.items() if flower_rarity == rarity]
        if event and random.random() < 0.18:
            return event["flower"], "Seasonal"
        if not candidates:
            candidates = ["Dandelion"]
        return random.choice(candidates), rarity

    def _make_reward(self, reward_type, seed_type, guild_data, event):
        min_amt = max(0, int(guild_data.get("min_credits", MIN_CREDITS)))
        max_amt = max(min_amt, int(guild_data.get("max_credits", MAX_CREDITS)))
        if reward_type == "currency":
            multiplier = 1.0 if seed_type == "common" else 1.5 if seed_type == "golden" else 1.0
            return {"kind": "currency", "amount": max(0, int(random.randint(min_amt, max_amt) * multiplier))}
        if reward_type == "prompt":
            return {"kind": "prompt", "text": random.choice(PROMPTS)}
        if reward_type == "fortune":
            return {"kind": "fortune", "text": random.choice(FORTUNES)}
        if reward_type == "advice":
            return {"kind": "advice", "text": random.choice(ADVICE)}
        if reward_type == "flower":
            flower, rarity = self._choose_flower(seed_type, event)
            return {"kind": "flower", "flower": flower, "rarity": rarity}
        if reward_type == "seed":
            return {"kind": "seed", "seed_type": self._choose_seed_type()}
        if reward_type == "xp":
            return {"kind": "xp", "amount": random.randint(15, 35)}
        if reward_type == "jackpot":
            lower = max(1, min_amt * 5)
            upper = max(lower, max_amt * 5)
            return {"kind": "jackpot", "amount": random.randint(lower, upper)}
        if reward_type == "mystery":
            prize_type = random.choice(["fertilizer", "seed", "flower", "xp"])
            if prize_type == "fertilizer":
                prize = {"kind": "fertilizer", "amount": 1}
            elif prize_type == "seed":
                prize = {"kind": "seed", "seed_type": self._choose_seed_type()}
            elif prize_type == "flower":
                flower, rarity = self._choose_flower(seed_type, event)
                prize = {"kind": "flower", "flower": flower, "rarity": rarity}
            else:
                prize = {"kind": "xp", "amount": random.randint(20, 45)}
            return {"kind": "mystery", "prize": prize}
        return {"kind": "advice", "text": random.choice(ADVICE)}

    def _roll_reward_type(self, guild_data, seed_type, fertilized=False):
        weights = guild_data.get("reward_weights") or DEFAULT_REWARD_WEIGHTS
        adjusted = dict(weights)
        if seed_type == "golden":
            adjusted["currency"] = float(adjusted.get("currency", 0)) * 1.5
            adjusted["jackpot"] = float(adjusted.get("jackpot", 0)) * 1.3
        elif seed_type == "moonlight":
            adjusted["flower"] = float(adjusted.get("flower", 0)) * 1.6
            adjusted["prompt"] = float(adjusted.get("prompt", 0)) * 1.25
        elif seed_type == "ancient":
            adjusted["flower"] = float(adjusted.get("flower", 0)) * 2.0
            adjusted["jackpot"] = float(adjusted.get("jackpot", 0)) * 2.0
            adjusted["mystery"] = float(adjusted.get("mystery", 0)) * 1.5
        if fertilized:
            adjusted["flower"] = float(adjusted.get("flower", 0)) * 2.0
        names = [name for name, weight in adjusted.items() if name in DEFAULT_REWARD_WEIGHTS and math.isfinite(float(weight)) and float(weight) > 0]
        values = [float(adjusted[name]) for name in names]
        if not names or sum(values) <= 0:
            names = list(DEFAULT_REWARD_WEIGHTS)
            values = list(DEFAULT_REWARD_WEIGHTS.values())
        return random.choices(names, weights=values, k=1)[0]

    async def _reward_text(self, reward, guild):
        kind = reward.get("kind")
        if kind in ("currency", "jackpot"):
            currency = await bank.get_currency_name(guild)
            label = "Jackpot" if kind == "jackpot" else "Currency"
            return f"💰 **{label}:** {reward.get('amount', 0)} {currency}"
        if kind == "prompt":
            return f"✏️ **Writing Prompt**\n> {reward.get('text', '')}"
        if kind == "fortune":
            return f"🔮 **Fortune**\n> {reward.get('text', '')}"
        if kind == "advice":
            return f"💡 **Advice**\n> {reward.get('text', '')}"
        if kind == "flower":
            return f"🌸 **{reward.get('rarity', 'Common')} Flower:** {reward.get('flower', 'Dandelion')}"
        if kind == "seed":
            seed_type = reward.get("seed_type", "common")
            return f"{SEED_TYPES.get(seed_type, SEED_TYPES['common'])['emoji']} **Bonus Seed:** {SEED_TYPES.get(seed_type, SEED_TYPES['common'])['label']}"
        if kind == "xp":
            return f"⭐ **Garden Experience:** {reward.get('amount', 0)} XP"
        if kind == "mystery":
            prize = reward.get("prize", {})
            prize_kind = prize.get("kind")
            if prize_kind == "fertilizer":
                return "🎁 **Mystery Box:** 1 Fertilizer"
            if prize_kind == "seed":
                seed_type = prize.get("seed_type", "common")
                return f"🎁 **Mystery Box:** {SEED_TYPES.get(seed_type, SEED_TYPES['common'])['label']}"
            if prize_kind == "flower":
                return f"🎁 **Mystery Box:** {prize.get('rarity', 'Common')} {prize.get('flower', 'Dandelion')}"
            if prize_kind == "xp":
                return f"🎁 **Mystery Box:** {prize.get('amount', 0)} Garden XP"
        return "A mysterious garden blessing."

    def _apply_prize(self, garden, prize, seed_limit):
        kind = prize.get("kind")
        if kind == "fertilizer":
            garden.setdefault("items", {})["fertilizer"] = int(garden.get("items", {}).get("fertilizer", 0)) + int(prize.get("amount", 1))
        elif kind == "seed":
            seed_type = prize.get("seed_type", "common")
            if self._seed_count(garden) < seed_limit:
                garden["seed_inventory"][seed_type] = garden["seed_inventory"].get(seed_type, 0) + 1
            else:
                self._add_xp(garden, 10)
        elif kind == "flower":
            self._add_flower(garden, prize.get("flower", "Dandelion"))
        elif kind == "xp":
            self._add_xp(garden, int(prize.get("amount", 0)))

    async def _apply_member_bloom(self, member, fid, reward, reward_text, event, seed_limit):
        lock = self._member_lock(member.guild.id, member.id)
        async with lock:
            member_conf = self.config.member(member)
            garden = await self._get_garden(member_conf)
            applied = garden.setdefault("applied_reward_ids", [])
            if fid in applied:
                return []

            kind = reward.get("kind")
            if kind == "flower":
                self._add_flower(garden, reward.get("flower", "Dandelion"))
            elif kind == "seed":
                seed_type = reward.get("seed_type", "common")
                if self._seed_count(garden) < seed_limit:
                    garden["seed_inventory"][seed_type] = garden["seed_inventory"].get(seed_type, 0) + 1
                else:
                    self._add_xp(garden, 10)
            elif kind == "xp":
                self._add_xp(garden, int(reward.get("amount", 0)))
            elif kind == "mystery":
                self._apply_prize(garden, reward.get("prize", {}), seed_limit)

            garden["total_blooms"] = int(garden.get("total_blooms", 0)) + 1
            self._add_xp(garden, 25)
            event_progress = garden.setdefault("event_progress", {})
            event_key = event["key"]
            event_progress[event_key] = int(event_progress.get(event_key, 0)) + 1
            event_claims = garden.setdefault("event_claims", [])
            points = event_progress[event_key]
            event_notes = []
            if points >= 5 and f"{event_key}:5" not in event_claims:
                self._add_flower(garden, event["flower"])
                event_claims.append(f"{event_key}:5")
                event_notes.append(f"{event['emoji']} Seasonal milestone: {event['flower']} discovered")
            if points >= 10 and f"{event_key}:10" not in event_claims:
                if self._seed_count(garden) < seed_limit:
                    garden["seed_inventory"]["golden"] = garden["seed_inventory"].get("golden", 0) + 1
                    event_notes.append("🌟 Seasonal milestone: Golden Seed earned")
                else:
                    self._add_xp(garden, 25)
                    event_notes.append("⭐ Seasonal milestone: 25 bonus garden XP")
                event_claims.append(f"{event_key}:10")
            if points >= 20 and f"{event_key}:20" not in event_claims:
                decoration = "Seasonal Moon Lantern"
                if decoration not in garden.setdefault("unlocked_decorations", []):
                    garden["unlocked_decorations"].append(decoration)
                    event_notes.append(f"🏮 Seasonal milestone: {decoration} unlocked")
                event_claims.append(f"{event_key}:20")

            garden.setdefault("reward_history", []).append({
                "seed_id": fid,
                "timestamp": datetime.utcnow().isoformat(),
                "reward": reward_text[:400],
            })
            garden["reward_history"] = garden["reward_history"][-20:]
            applied.append(fid)
            garden["applied_reward_ids"] = applied[-500:]
            achievements = self._check_achievements(garden)
            await self._save_garden(member_conf, garden)
            return achievements + event_notes

    async def _resolve_member(self, guild, member_id):
        try:
            member_id = int(member_id)
        except (TypeError, ValueError):
            return None
        member = guild.get_member(member_id)
        if member:
            return member
        try:
            return await guild.fetch_member(member_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    async def _resolve_delivery_targets(self, guild, member, info, guild_data):
        configured = guild_data.get("reward_channel")
        candidates = [configured, info.get("channel_id")]
        targets = []
        seen = set()
        for channel_id in candidates:
            if not channel_id or int(channel_id) in seen:
                continue
            seen.add(int(channel_id))
            channel = guild.get_channel(int(channel_id))
            if channel is None:
                channel = guild.get_thread(int(channel_id))
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(int(channel_id))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    channel = None
            if channel is not None and getattr(channel, "guild", None) and channel.guild.id == guild.id and hasattr(channel, "send"):
                targets.append(channel)
        targets.append(member)
        return targets

    async def _process_due_seeds(self):
        now = datetime.utcnow()
        all_guilds = await self.config.all_guilds()
        for guild_id in list(all_guilds):
            lock = self._guild_lock(guild_id)
            async with lock:
                guild = self.bot.get_guild(int(guild_id))
                if guild is None:
                    continue
                guild_conf = self.config.guild_from_id(int(guild_id))
                guild_data = await guild_conf.all()
                fortunes = guild_data.get("fortunes", {})
                changed = False
                seed_limit = int(guild_data.get("seed_limit", 20))
                event = current_seasonal_event(now)

                for fid, info in list(fortunes.items()):
                    try:
                        bloom_time = datetime.fromisoformat(info["bloom_time"])
                    except (KeyError, TypeError, ValueError):
                        log.error("Fortune seed %s in guild %s has an invalid bloom time.", fid, guild_id)
                        info["last_error"] = "Invalid bloom time"
                        changed = True
                        continue

                    if info.get("processed"):
                        if bloom_time < now - timedelta(days=7):
                            fortunes.pop(fid, None)
                            changed = True
                        continue
                    if now < bloom_time:
                        continue

                    member = await self._resolve_member(guild, info.get("owner_id"))
                    if member is None:
                        info["last_error"] = "Owner is not currently available in the server"
                        info["attempts"] = int(info.get("attempts", 0)) + 1
                        changed = True
                        continue

                    seed_type = info.get("seed_type", "common")
                    if not isinstance(info.get("reward"), dict):
                        reward_type = self._roll_reward_type(guild_data, seed_type, bool(info.get("fertilized")))
                        reward = self._make_reward(reward_type, seed_type, guild_data, event)
                        if info.get("fertilized"):
                            flower_reward = reward if reward.get("kind") == "flower" else reward.get("prize", {}) if reward.get("kind") == "mystery" else {}
                            if flower_reward.get("kind") == "flower":
                                flower, rarity = self._choose_flower("golden", event)
                                flower_reward["flower"] = flower
                                flower_reward["rarity"] = rarity
                        info["reward"] = reward
                        info["reward_created_at"] = now.isoformat()
                        changed = True
                        await guild_conf.fortunes.set(fortunes)

                    reward = info["reward"]
                    reward_text = await self._reward_text(reward, guild)
                    if reward.get("kind") in ("currency", "jackpot") and not info.get("currency_applied"):
                        if info.get("currency_claimed"):
                            info["currency_review"] = True
                            info["last_error"] = "Currency payout was claimed before an interrupted deposit; manual review required"
                            changed = True
                            log.error("Currency reward for seed %s in guild %s requires manual review.", fid, guild_id)
                            continue
                        info["currency_claimed"] = True
                        info["currency_claimed_at"] = now.isoformat()
                        await guild_conf.fortunes.set(fortunes)
                        try:
                            await bank.deposit_credits(member, int(reward.get("amount", 0)))
                            info["currency_applied"] = True
                            info.pop("currency_review", None)
                            info.pop("last_error", None)
                            changed = True
                            await guild_conf.fortunes.set(fortunes)
                        except Exception as exc:
                            info["currency_review"] = True
                            info["last_error"] = f"Currency deposit failed: {exc}"[:300]
                            changed = True
                            await guild_conf.fortunes.set(fortunes)
                            log.error("Currency reward failed for seed %s in guild %s: %s", fid, guild_id, exc, exc_info=True)
                            continue

                    if not info.get("member_applied"):
                        try:
                            notes = await self._apply_member_bloom(member, fid, reward, reward_text, event, seed_limit)
                            info["member_applied"] = True
                            info["bloom_notes"] = notes
                            changed = True
                            await guild_conf.fortunes.set(fortunes)
                        except Exception as exc:
                            info["last_error"] = f"Member reward update failed: {exc}"[:300]
                            changed = True
                            await guild_conf.fortunes.set(fortunes)
                            log.error("Member reward update failed for seed %s: %s", fid, exc, exc_info=True)
                            continue

                    embed = discord.Embed(
                        title="🌸 Your Fortune Seed Has Bloomed!",
                        description=f"Your planted {SEED_TYPES.get(seed_type, SEED_TYPES['common'])['label']} has finished growing.",
                        color=discord.Color.random(),
                        timestamp=datetime.utcnow(),
                    )
                    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
                    embed.add_field(name="Your Reward", value=reward_text, inline=False)
                    if info.get("bloom_notes"):
                        embed.add_field(name="Garden Discoveries", value="\n".join(info["bloom_notes"])[:1024], inline=False)
                    if info.get("seed_name"):
                        embed.add_field(name="Plant Name", value=discord.utils.escape_markdown(str(info["seed_name"]))[:100], inline=True)
                    embed.set_image(url=REWARD_BANNERS.get(reward.get("kind"), REWARD_BANNERS["flower"]))
                    embed.set_footer(text=f"Seed ID: {fid} • Event: {event['name']}")

                    targets = await self._resolve_delivery_targets(guild, member, info, guild_data)
                    delivery_error = None
                    delivered = False
                    for target in targets:
                        try:
                            if target is member:
                                await member.send(embed=embed)
                            else:
                                await target.send(content=member.mention, embed=embed)
                            delivered = True
                            break
                        except discord.Forbidden as exc:
                            delivery_error = f"Reward delivery forbidden: {exc}"[:300]
                            continue
                        except discord.HTTPException as exc:
                            delivery_error = f"Reward delivery failed: {exc}"[:300]
                            break
                    if not delivered:
                        info["last_error"] = delivery_error or "No delivery destination is available"
                        info["attempts"] = int(info.get("attempts", 0)) + 1
                        changed = True
                        continue

                    info["processed"] = True
                    info["processed_at"] = datetime.utcnow().isoformat()
                    info["attempts"] = int(info.get("attempts", 0)) + 1
                    info.pop("last_error", None)
                    changed = True

                if changed:
                    await guild_conf.fortunes.set(fortunes)

    @tasks.loop(seconds=60.0)
    async def bloom_loop(self):
        try:
            await self._process_due_seeds()
        except Exception:
            log.exception("FortuneGarden bloom processor failed; it will retry on the next cycle.")

    @bloom_loop.before_loop
    async def before_bloom(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.webhook_id or not message.guild:
            return
        content = (message.content or "").strip()
        if not content:
            return
        prefixes = await self.bot.get_prefix(message)
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        if any(content.startswith(prefix) for prefix in prefixes if prefix):
            return

        guild_conf = self.config.guild(message.guild)
        guild_data = await guild_conf.all()
        if not guild_data.get("enabled", True):
            return
        min_length = max(0, int(guild_data.get("min_message_length", 8)))
        if len(content) < min_length:
            return
        ignored_channels = {int(value) for value in guild_data.get("ignored_channels", [])}
        channel_ids = {message.channel.id}
        parent_id = getattr(message.channel, "parent_id", None)
        if parent_id:
            channel_ids.add(parent_id)
        if channel_ids.intersection(ignored_channels):
            return
        ignored_roles = {int(value) for value in guild_data.get("ignored_roles", [])}
        if any(role.id in ignored_roles for role in getattr(message.author, "roles", [])):
            return

        lock = self._member_lock(message.guild.id, message.author.id)
        async with lock:
            member_conf = self.config.member(message.author)
            member_data = await member_conf.all()
            if member_data.get("opt_out"):
                return
            garden = await self._get_garden(member_conf)
            seed_limit = max(0, int(guild_data.get("seed_limit", 20)))
            if garden["seeds"] >= seed_limit:
                return
            last = member_data.get("last_earned")
            now = datetime.utcnow()
            if last:
                try:
                    last_dt = datetime.fromisoformat(last)
                    if now - last_dt < timedelta(minutes=max(0, int(guild_data.get("seed_cooldown", 60)))):
                        return
                except (TypeError, ValueError):
                    pass
            chance = max(0.0, min(100.0, float(guild_data.get("seed_chance", 5.0))))
            if random.random() * 100 >= chance:
                return
            seed_type = self._choose_seed_type()
            garden["seed_inventory"][seed_type] = garden["seed_inventory"].get(seed_type, 0) + 1
            await self._save_garden(member_conf, garden)
            await member_conf.last_earned.set(now.isoformat())
            template = guild_data.get("discover_message") or DEFAULT_DISCOVER_MSG
            prefixes = await self.bot.get_prefix(message)
            prefix = prefixes[0] if isinstance(prefixes, (list, tuple)) and prefixes else str(prefixes)
            plural = "s" if garden["seeds"] != 1 else ""
            values = {
                "mention": message.author.mention,
                "seeds": garden["seeds"],
                "plural": plural,
                "prefix": prefix,
                "seed_type": SEED_TYPES[seed_type]["label"],
                "seed_emoji": SEED_TYPES[seed_type]["emoji"],
            }
            try:
                content_out = template.format(**values)
            except (KeyError, IndexError, ValueError):
                content_out = DEFAULT_DISCOVER_MSG.format(**values)
            try:
                await message.channel.send(content_out)
            except discord.HTTPException:
                log.warning("Could not send seed discovery message in channel %s.", message.channel.id)

    @commands.guild_only()
    @commands.command(name="fortuneseeds", help="Show your fortune seed inventory or another member's.")
    async def fortuneseeds(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        lock = self._member_lock(ctx.guild.id, member.id)
        async with lock:
            garden = await self._get_garden(self.config.member(member))
        embed = discord.Embed(
            title="🌱 Fortune Seed Inventory",
            description=f"{member.mention} has **{garden['seeds']}** seed{'s' if garden['seeds'] != 1 else ''}.",
            color=discord.Color.random(),
        )
        for seed_type, details in SEED_TYPES.items():
            embed.add_field(name=f"{details['emoji']} {details['label']}", value=str(garden["seed_inventory"].get(seed_type, 0)), inline=True)
        embed.set_image(url=SEED_BANNER)
        await ctx.send(embed=embed)

    @commands.guild_only()
    @commands.command(name="plantfortune", help="Plant a seed. Usage: plantfortune [common|golden|moonlight|ancient] [name]")
    async def plantfortune(self, ctx, seed_type: str = "common", *, name: str = None):
        seed_type = (seed_type or "common").lower()
        if seed_type not in SEED_TYPES:
            name = f"{seed_type} {name}".strip() if name else seed_type
            seed_type = "common"
        name = name.strip()[:50] if name else None
        guild_lock = self._guild_lock(ctx.guild.id)
        member_lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with guild_lock:
            async with member_lock:
                member_conf = self.config.member(ctx.author)
                garden = await self._get_garden(member_conf)
                if garden["seed_inventory"].get(seed_type, 0) < 1:
                    available = ", ".join(f"{SEED_TYPES[key]['emoji']} {SEED_TYPES[key]['label']}: {value}" for key, value in garden["seed_inventory"].items() if value > 0)
                    if not available:
                        return await ctx.send(f"{ctx.author.mention}, you have no fortune seeds! Chat to discover one.")
                    return await ctx.send(f"You don't have a {SEED_TYPES[seed_type]['label']}. Your inventory: {available}")
                guild_conf = self.config.guild(ctx.guild)
                guild_data = await guild_conf.all()
                pending = sum(1 for info in guild_data.get("fortunes", {}).values() if info.get("owner_id") == ctx.author.id and not info.get("processed"))
                if pending >= 20:
                    return await ctx.send("You already have 20 seeds growing. Let some bloom before planting more.")
                min_hours = max(1, int(guild_data.get("min_bloom_hours", 1)))
                max_hours = max(min_hours, int(guild_data.get("max_bloom_hours", 12)))
                delay_hours = random.uniform(min_hours, max_hours)
                if seed_type == "golden":
                    delay_hours *= 0.85
                elif seed_type == "moonlight":
                    delay_hours *= 1.05
                elif seed_type == "ancient":
                    delay_hours *= 1.15
                now = datetime.utcnow()
                bloom_time = now + timedelta(hours=delay_hours)
                fortunes = guild_data.get("fortunes", {})
                fid = f"{int(now.timestamp() * 1000)}-{random.randint(1000, 9999)}"
                while fid in fortunes:
                    fid = f"{int(datetime.utcnow().timestamp() * 1000)}-{random.randint(1000, 9999)}"
                fortunes[fid] = {
                    "owner_id": ctx.author.id,
                    "channel_id": ctx.channel.id,
                    "bloom_time": bloom_time.isoformat(),
                    "processed": False,
                    "seed_type": seed_type,
                    "seed_name": name,
                    "fertilized": False,
                    "attempts": 0,
                }
                garden["seed_inventory"][seed_type] -= 1
                garden["total_planted"] = int(garden.get("total_planted", 0)) + 1
                self._add_xp(garden, 5)
                achievements = self._check_achievements(garden)
                await self._save_garden(member_conf, garden)
                await guild_conf.fortunes.set(fortunes)
                remaining = garden["seed_inventory"][seed_type]
                seed_total = garden["seeds"]
        hours = int(delay_hours)
        minutes = int((delay_hours - hours) * 60)
        duration = f"{hours}h {minutes}m" if minutes else f"{hours}h"
        embed = discord.Embed(
            title="🌱 Seed Planted",
            description=f"{ctx.author.mention}, your **{SEED_TYPES[seed_type]['label']}** will bloom in approximately **{duration}**.",
            color=discord.Color.random(),
        )
        if name:
            embed.add_field(name="Plant Name", value=discord.utils.escape_markdown(name), inline=False)
        embed.add_field(name="Seed ID", value=fid, inline=True)
        embed.add_field(name="Seeds Left", value=str(seed_total), inline=True)
        embed.add_field(name="This Seed Type Left", value=str(remaining), inline=True)
        if achievements:
            embed.add_field(name="Achievements Unlocked", value="\n".join(f"🏅 {item}" for item in achievements), inline=False)
        embed.set_image(url=PLANT_BANNER)
        await ctx.send(embed=embed)

    @commands.guild_only()
    @commands.command(name="listfortunes", help="List your growing and recently bloomed seeds.")
    async def listfortunes(self, ctx):
        guild_data = await self.config.guild(ctx.guild).all()
        now = datetime.utcnow()
        entries = []
        for fid, info in guild_data.get("fortunes", {}).items():
            if int(info.get("owner_id", 0)) != ctx.author.id:
                continue
            try:
                bloom_time = datetime.fromisoformat(info["bloom_time"])
            except (KeyError, TypeError, ValueError):
                continue
            seed_label = SEED_TYPES.get(info.get("seed_type", "common"), SEED_TYPES["common"])["label"]
            if info.get("processed"):
                status = "🌸 Bloomed"
            elif info.get("currency_review"):
                status = "⚠️ Reward needs admin review"
            else:
                remaining = max(0, int((bloom_time - now).total_seconds()))
                hours, rest = divmod(remaining, 3600)
                minutes = rest // 60
                status = f"⌛ {hours}h {minutes}m left"
            entries.append((bloom_time, f"**{seed_label}** • `{fid}` — {status}"))
        entries.sort(key=lambda item: item[0])
        if not entries:
            return await ctx.send("You have no active or recently bloomed fortune seeds.")
        pages = []
        for start in range(0, len(entries), 10):
            page_entries = entries[start:start + 10]
            embed = discord.Embed(
                title="🌱 Your Planted Seeds",
                description="\n".join(item[1] for item in page_entries),
                color=discord.Color.random(),
            )
            embed.set_footer(text=f"Page {len(pages) + 1}/{(len(entries) + 9) // 10}")
            embed.set_image(url=LIST_BANNER)
            pages.append(embed)
        if len(pages) == 1:
            return await ctx.send(embed=pages[0])
        view = FortunePaginator(ctx.author.id, pages)
        view.message = await ctx.send(embed=pages[0], view=view)

    @commands.guild_only()
    @commands.command(name="removefortune", help="Remove one of your unbloomed seeds by ID and return it to its owner's inventory.")
    async def removefortune(self, ctx, fid: str):
        guild_lock = self._guild_lock(ctx.guild.id)
        async with guild_lock:
            guild_conf = self.config.guild(ctx.guild)
            fortunes = await guild_conf.fortunes()
            info = fortunes.get(fid)
            if not info:
                return await ctx.send("No fortune seed with that ID.")
            owner_id = int(info.get("owner_id", 0))
            if owner_id != ctx.author.id and not ctx.author.guild_permissions.manage_guild:
                return await ctx.send("You don't have permission to remove this seed.")
            if info.get("processed"):
                return await ctx.send("That seed has already bloomed and cannot be removed.")
            if info.get("currency_claimed"):
                return await ctx.send("That seed is already being processed and cannot safely be removed.")
            owner = await self._resolve_member(ctx.guild, owner_id)
            if owner is None:
                return await ctx.send("The seed owner is not currently in the server, so the seed cannot safely be returned.")
            owner_lock = self._member_lock(ctx.guild.id, owner_id)
            async with owner_lock:
                member_conf = self.config.member(owner)
                garden = await self._get_garden(member_conf)
                seed_type = info.get("seed_type", "common")
                if seed_type not in SEED_TYPES:
                    seed_type = "common"
                garden["seed_inventory"][seed_type] = garden["seed_inventory"].get(seed_type, 0) + 1
                await self._save_garden(member_conf, garden)
                fortunes.pop(fid)
                await guild_conf.fortunes.set(fortunes)
        await ctx.send(f"🗑️ Removed fortune seed `{fid}` and returned it to {owner.mention}'s inventory.")

    @commands.guild_only()
    @commands.command(name="waterfortune", help="Water one growing seed once per day to speed it up and earn garden XP.")
    async def waterfortune(self, ctx, fid: str):
        guild_lock = self._guild_lock(ctx.guild.id)
        member_lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with guild_lock:
            async with member_lock:
                guild_conf = self.config.guild(ctx.guild)
                fortunes = await guild_conf.fortunes()
                info = fortunes.get(fid)
                if not info or int(info.get("owner_id", 0)) != ctx.author.id:
                    return await ctx.send("You don't have a growing seed with that ID.")
                if info.get("processed"):
                    return await ctx.send("That seed has already bloomed.")
                member_conf = self.config.member(ctx.author)
                garden = await self._get_garden(member_conf)
                today = datetime.utcnow().date().isoformat()
                if garden.get("daily_water_date") == today:
                    return await ctx.send("💧 You have already used today's watering bonus. Come back tomorrow!")
                try:
                    old_time = datetime.fromisoformat(info["bloom_time"])
                except (KeyError, TypeError, ValueError):
                    return await ctx.send("That seed has an invalid bloom timer and cannot be watered.")
                guild_data = await guild_conf.all()
                minutes_saved = max(1, int(guild_data.get("watering_minutes", 30)))
                info["bloom_time"] = max(datetime.utcnow(), old_time - timedelta(minutes=minutes_saved)).isoformat()
                garden["daily_water_date"] = today
                last_water = garden.get("last_water_date")
                yesterday = (datetime.utcnow().date() - timedelta(days=1)).isoformat()
                garden["water_streak"] = int(garden.get("water_streak", 0)) + 1 if last_water == yesterday else 1
                garden["last_water_date"] = today
                self._add_xp(garden, 5)
                bonus = None
                if garden["water_streak"] % 7 == 0:
                    garden.setdefault("items", {})["fertilizer"] = int(garden.get("items", {}).get("fertilizer", 0)) + 1
                    bonus = " Your seven-day streak earned you **1 Fertilizer**!"
                achievements = self._check_achievements(garden)
                await self._save_garden(member_conf, garden)
                await guild_conf.fortunes.set(fortunes)
                remaining = max(0, int((datetime.fromisoformat(info["bloom_time"]) - datetime.utcnow()).total_seconds()))
        hours, rest = divmod(remaining, 3600)
        await ctx.send(f"💧 You watered your seed and saved up to **{minutes_saved} minutes**. It now has **{hours}h {rest // 60}m** remaining. You earned **5 garden XP**.{bonus or ''}" + (f"\n🏅 Unlocked: {', '.join(achievements)}" if achievements else ""))

    @commands.guild_only()
    @commands.command(name="fertilizefortune", help="Use one fertilizer on a growing seed to speed it up and improve its flower odds.")
    async def fertilizefortune(self, ctx, fid: str):
        guild_lock = self._guild_lock(ctx.guild.id)
        member_lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with guild_lock:
            async with member_lock:
                guild_conf = self.config.guild(ctx.guild)
                fortunes = await guild_conf.fortunes()
                info = fortunes.get(fid)
                if not info or int(info.get("owner_id", 0)) != ctx.author.id:
                    return await ctx.send("You don't have a growing seed with that ID.")
                if info.get("processed"):
                    return await ctx.send("That seed has already bloomed.")
                if info.get("fertilized"):
                    return await ctx.send("That seed has already been fertilized.")
                member_conf = self.config.member(ctx.author)
                garden = await self._get_garden(member_conf)
                items = garden.setdefault("items", {})
                if int(items.get("fertilizer", 0)) < 1:
                    return await ctx.send("You don't have any Fertilizer. Find some in a Mystery Box or a watering streak reward.")
                try:
                    old_time = datetime.fromisoformat(info["bloom_time"])
                except (KeyError, TypeError, ValueError):
                    return await ctx.send("That seed has an invalid bloom timer and cannot be fertilized.")
                guild_data = await guild_conf.all()
                minutes_saved = max(1, int(guild_data.get("fertilizing_minutes", 60)))
                info["bloom_time"] = max(datetime.utcnow(), old_time - timedelta(minutes=minutes_saved)).isoformat()
                info["fertilized"] = True
                items["fertilizer"] = int(items.get("fertilizer", 0)) - 1
                self._add_xp(garden, 5)
                await self._save_garden(member_conf, garden)
                await guild_conf.fortunes.set(fortunes)
        await ctx.send(f"🌿 Fertilizer used! Your seed's bloom time was reduced by up to **{minutes_saved} minutes**, and its flower reward odds have improved.")

    @commands.guild_only()
    @commands.command(name="forgarden", aliases=["mygarden"], help="View your personal FortuneGarden, level, collection and progress.")
    async def forgarden(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        lock = self._member_lock(ctx.guild.id, member.id)
        async with lock:
            garden = await self._get_garden(self.config.member(member))
        unique_flowers = sum(1 for count in garden.get("flowers", {}).values() if count > 0)
        total_flowers = sum(int(count) for count in garden.get("flowers", {}).values())
        xp = int(garden.get("garden_xp", 0))
        current_level_xp = xp % 100
        event = current_seasonal_event()
        event_points = int(garden.get("event_progress", {}).get(event["key"], 0))
        embed = discord.Embed(
            title=f"🏡 {member.display_name}'s FortuneGarden",
            description=f"{event['emoji']} **Current event:** {event['name']}\n{garden.get('equipped_decoration') or 'A peaceful, growing garden'}",
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="🌱 Seeds", value=f"**{garden['seeds']}**\n" + " • ".join(f"{SEED_TYPES[key]['emoji']} {garden['seed_inventory'].get(key, 0)}" for key in SEED_TYPES), inline=False)
        embed.add_field(name="⭐ Garden Level", value=f"**Level {garden['garden_level']}**\n{current_level_xp}/100 XP", inline=True)
        embed.add_field(name="🌸 Flowers", value=f"{total_flowers} collected\n{unique_flowers} unique", inline=True)
        embed.add_field(name="🌿 Growth", value=f"{garden.get('total_planted', 0)} planted\n{garden.get('total_blooms', 0)} bloomed", inline=True)
        embed.add_field(name="🏅 Achievements", value=str(len(garden.get("achievements", []))), inline=True)
        embed.add_field(name="💧 Water Streak", value=f"{garden.get('water_streak', 0)} day(s)", inline=True)
        embed.add_field(name="🎁 Fertilizer", value=str(garden.get("items", {}).get("fertilizer", 0)), inline=True)
        embed.add_field(name="🎪 Event Progress", value=f"{event_points}/5 toward a seasonal flower\n{max(0, 5 - event_points % 5)} bloom(s) to next milestone", inline=False)
        unlocked = garden.get("unlocked_decorations", [])
        embed.add_field(name="🪴 Decorations", value=", ".join(unlocked[-5:]) if unlocked else "Reach higher garden levels to unlock decorations.", inline=False)
        if garden.get("flowers"):
            preview = sorted(garden["flowers"].items(), key=lambda item: (list(FLOWERS.values()).index(FLOWERS.get(item[0], "Common")), item[0]))[:8]
            embed.add_field(name="Recent Collection", value=" • ".join(f"{name} ×{count}" for name, count in preview), inline=False)
        await ctx.send(embed=embed)

    @commands.guild_only()
    @commands.command(name="gardenflowers", aliases=["flowercollection"], help="View the flowers in your collection.")
    async def gardenflowers(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        lock = self._member_lock(ctx.guild.id, member.id)
        async with lock:
            garden = await self._get_garden(self.config.member(member))
        flowers = garden.get("flowers", {})
        if not flowers:
            return await ctx.send(f"{member.mention} hasn't discovered any flowers yet. Plant seeds and wait for them to bloom!")
        rarity_order = {"Legendary": 0, "Epic": 1, "Rare": 2, "Uncommon": 3, "Seasonal": 4, "Common": 5}
        lines = [f"**{FLOWERS.get(name, 'Common')}** — {name} ×{count}" for name, count in sorted(flowers.items(), key=lambda item: (rarity_order.get(FLOWERS.get(item[0], 'Common'), 9), item[0])) if count > 0]
        embed = discord.Embed(title=f"🌸 {member.display_name}'s Flower Collection", description="\n".join(lines)[:4000], color=discord.Color.random())
        embed.set_footer(text=f"{len(flowers)} unique flower varieties • {sum(flowers.values())} total flowers")
        await ctx.send(embed=embed)

    @commands.guild_only()
    @commands.command(name="gardenachievements", aliases=["fortuneachievements"], help="View your unlocked FortuneGarden achievements.")
    async def gardenachievements(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        lock = self._member_lock(ctx.guild.id, member.id)
        async with lock:
            garden = await self._get_garden(self.config.member(member))
        earned = garden.get("achievements", [])
        lines = [f"🏅 **{name}** — {ACHIEVEMENT_DESCRIPTIONS.get(name, '')}" for name in earned]
        remaining = [f"🔒 **{name}** — {description}" for name, description in ACHIEVEMENT_DESCRIPTIONS.items() if name not in earned]
        embed = discord.Embed(title=f"🏆 {member.display_name}'s Achievements", description=("\n".join(lines) if lines else "No achievements unlocked yet.") + ("\n\n" + "\n".join(remaining) if remaining else ""), color=discord.Color.gold())
        await ctx.send(embed=embed)

    @commands.guild_only()
    @commands.command(name="fortunehistory", help="View your most recent FortuneGarden rewards.")
    async def fortunehistory(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        lock = self._member_lock(ctx.guild.id, member.id)
        async with lock:
            garden = await self._get_garden(self.config.member(member))
        history = garden.get("reward_history", [])[-10:]
        if not history:
            return await ctx.send("You don't have any recorded bloom rewards yet.")
        lines = []
        for item in reversed(history):
            try:
                stamp = datetime.fromisoformat(item["timestamp"]).strftime("%Y-%m-%d %H:%M UTC")
            except (KeyError, ValueError, TypeError):
                stamp = "Unknown date"
            lines.append(f"`{stamp}` — {item.get('reward', 'Unknown reward')}\nSeed `{item.get('seed_id', '?')}`")
        embed = discord.Embed(title=f"📜 {member.display_name}'s Reward History", description="\n\n".join(lines)[:4000], color=discord.Color.random())
        await ctx.send(embed=embed)

    @commands.guild_only()
    @commands.command(name="fortuneevent", help="Show the current seasonal event and your progress.")
    async def fortuneevent(self, ctx):
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            garden = await self._get_garden(self.config.member(ctx.author))
        event = current_seasonal_event()
        points = int(garden.get("event_progress", {}).get(event["key"], 0))
        embed = discord.Embed(title=f"{event['emoji']} {event['name']}", description=f"Grow seeds during this seasonal event to earn exclusive rewards.\n\n**Your progress:** {points} event blooms\n**5 blooms:** {event['flower']}\n**10 blooms:** Golden Seed\n**20 blooms:** Seasonal Moon Lantern", color=discord.Color.random())
        await ctx.send(embed=embed)

    @commands.guild_only()
    @commands.command(name="gardendecorate", help="Equip an unlocked garden decoration. Use 'list' to view options or 'none' to unequip.")
    async def gardendecorate(self, ctx, *, decoration: str = "list"):
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            member_conf = self.config.member(ctx.author)
            garden = await self._get_garden(member_conf)
            unlocked = garden.get("unlocked_decorations", [])
            if decoration.lower() == "list":
                return await ctx.send("**Unlocked decorations:** " + (", ".join(unlocked) if unlocked else "None yet. Level up your garden to unlock decorations."))
            if decoration.lower() == "none":
                garden["equipped_decoration"] = None
                await self._save_garden(member_conf, garden)
                return await ctx.send("Your garden decoration has been unequipped.")
            match = next((item for item in unlocked if item.lower() == decoration.lower()), None)
            if not match:
                return await ctx.send("You haven't unlocked that decoration. Use `gardendecorate list` to see your options.")
            garden["equipped_decoration"] = match
            await self._save_garden(member_conf, garden)
        await ctx.send(f"🏡 **{match}** is now displayed in your garden.")

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="setfortunepayout", help="Set the minimum and maximum currency reward.")
    async def setfortunepayout(self, ctx, min_amt: int, max_amt: int):
        if min_amt < 0 or max_amt < min_amt or max_amt > 1000000000:
            return await ctx.send("⚠️ Invalid range. Ensure 0 ≤ minimum ≤ maximum ≤ 1,000,000,000.")
        guild_conf = self.config.guild(ctx.guild)
        await guild_conf.min_credits.set(min_amt)
        await guild_conf.max_credits.set(max_amt)
        await ctx.send(f"✅ Fortune payout range updated to **{min_amt}–{max_amt}** credits.")

    @commands.is_owner()
    @commands.command(name="flushfortunes", help="Force the bloom processor to run immediately.")
    async def flushfortunes(self, ctx):
        await self._process_due_seeds()
        await ctx.send("🔄 Fortune loop flushed. All currently due seeds were checked.")

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="setfortunemessage", help="Customize the discovery message. Placeholders: {mention}, {seeds}, {plural}, {prefix}, {seed_type}, {seed_emoji}. Empty resets it.")
    async def setfortunemessage(self, ctx, *, template: str = None):
        new_template = template.strip() if template else None
        if new_template:
            allowed = {"mention", "seeds", "plural", "prefix", "seed_type", "seed_emoji"}
            try:
                fields = {field for _, field, _, _ in string.Formatter().parse(new_template) if field}
                new_template.format(mention="@user", seeds=1, plural="", prefix="!", seed_type="Common Seed", seed_emoji="🌱")
            except (ValueError, KeyError, IndexError):
                return await ctx.send("⚠️ That message template has invalid formatting.")
            if not {"mention", "seeds"}.issubset(fields) or not fields.issubset(allowed):
                return await ctx.send("⚠️ Include `{mention}` and `{seeds}` and use only supported placeholders: " + ", ".join(f"`{{{item}}}`" for item in sorted(allowed)))
        await self.config.guild(ctx.guild).discover_message.set(new_template)
        await ctx.send("✅ Fortune discovery message updated." if new_template else "✅ Fortune discovery message reset to default.")

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="fortunetoggle", help="Enable or disable seed drops for this server.")
    async def fortunetoggle(self, ctx, state: str = None):
        guild_conf = self.config.guild(ctx.guild)
        current = await guild_conf.enabled()
        if state is None or state.lower() in ("help", "h", "status"):
            status = "enabled" if current else "disabled"
            return await ctx.send(f"FortuneGarden is currently **{status}**. Use `fortunetoggle on` or `fortunetoggle off`.")
        state = state.lower()
        if state in ("on", "true", "enable"):
            await guild_conf.enabled.set(True)
            return await ctx.send("✅ FortuneGarden seed drops are now enabled.")
        if state in ("off", "false", "disable"):
            await guild_conf.enabled.set(False)
            return await ctx.send("🚫 FortuneGarden seed drops are now disabled. Planted seeds will still bloom.")
        await ctx.send("⚠️ Use `fortunetoggle on`, `fortunetoggle off`, or `fortunetoggle status`.")

    @commands.guild_only()
    @commands.command(name="seedopt", help="Manage receiving fortune seeds. Usage: seedopt off|on|status|help")
    async def seedopt(self, ctx, choice: str = None):
        member_conf = self.config.member(ctx.author)
        current = await member_conf.opt_out()
        choice = (choice or "help").lower()
        if choice in ("help", "h"):
            return await ctx.send("**SeedOpt Help**\n`seedopt off` — stop receiving seeds.\n`seedopt on` — start receiving seeds again.\n`seedopt status` — check your current setting.")
        if choice in ("off", "false", "optout", "out"):
            await member_conf.opt_out.set(True)
            return await ctx.send("🚫 You have opted out of receiving fortune seeds.")
        if choice in ("on", "true", "optin", "in"):
            await member_conf.opt_out.set(False)
            return await ctx.send("✅ You have opted in to receiving fortune seeds.")
        if choice == "status":
            return await ctx.send(f"ℹ️ You are currently **{'opted out' if current else 'opted in'}** of receiving seeds.")
        await ctx.send("⚠️ Use `seedopt help` for instructions.")

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="fortunesettings", help="Display the current FortuneGarden server configuration.")
    async def fortunesettings(self, ctx):
        data = await self.config.guild(ctx.guild).all()
        weights = data.get("reward_weights", DEFAULT_REWARD_WEIGHTS)
        channel = ctx.guild.get_channel(data.get("reward_channel")) if data.get("reward_channel") else None
        embed = discord.Embed(title="⚙️ FortuneGarden Settings", color=discord.Color.blurple())
        embed.add_field(name="Seed Drops", value=f"Enabled: **{data.get('enabled', True)}**\nChance: **{data.get('seed_chance', 5)}%**\nCooldown: **{data.get('seed_cooldown', 60)} minutes**\nInventory limit: **{data.get('seed_limit', 20)}**\nMinimum message length: **{data.get('min_message_length', 8)}**", inline=False)
        embed.add_field(name="Bloom Timer", value=f"{data.get('min_bloom_hours', 1)}–{data.get('max_bloom_hours', 12)} hours", inline=True)
        embed.add_field(name="Garden Boosts", value=f"Water: {data.get('watering_minutes', 30)} min\nFertilizer: {data.get('fertilizing_minutes', 60)} min", inline=True)
        embed.add_field(name="Payout", value=f"{data.get('min_credits', MIN_CREDITS)}–{data.get('max_credits', MAX_CREDITS)} credits", inline=True)
        embed.add_field(name="Reward Channel", value=channel.mention if channel else "Original planting channel / DM fallback", inline=True)
        embed.add_field(name="Reward Weights", value="\n".join(f"{key}: {value}" for key, value in weights.items())[:1024], inline=False)
        embed.add_field(name="Ignored Channels / Roles", value=f"{len(data.get('ignored_channels', []))} channel(s) / {len(data.get('ignored_roles', []))} role(s)", inline=True)
        await ctx.send(embed=embed)

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="setseedchance", help="Set the per-message seed drop chance as a percentage (0–100).")
    async def setseedchance(self, ctx, chance: float):
        if not 0 <= chance <= 100:
            return await ctx.send("⚠️ The chance must be between 0 and 100.")
        await self.config.guild(ctx.guild).seed_chance.set(float(chance))
        await ctx.send(f"✅ Seed drop chance set to **{chance:g}%** per eligible message.")

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="setseedminlength", help="Set the minimum message length required for seed drops.")
    async def setseedminlength(self, ctx, length: int):
        if not 0 <= length <= 500:
            return await ctx.send("⚠️ Minimum message length must be between 0 and 500 characters.")
        await self.config.guild(ctx.guild).min_message_length.set(length)
        await ctx.send(f"✅ Eligible messages must now contain at least **{length} characters**.")

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="setseedcooldown", help="Set the successful seed-drop cooldown in minutes.")
    async def setseedcooldown(self, ctx, minutes: int):
        if not 0 <= minutes <= 43200:
            return await ctx.send("⚠️ Cooldown must be between 0 and 43,200 minutes.")
        await self.config.guild(ctx.guild).seed_cooldown.set(minutes)
        await ctx.send(f"✅ Seed cooldown set to **{minutes} minutes**.")

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="setseedlimit", help="Set the maximum number of unplanted seeds a member can hold.")
    async def setseedlimit(self, ctx, limit: int):
        if not 1 <= limit <= 500:
            return await ctx.send("⚠️ Seed inventory limit must be between 1 and 500.")
        await self.config.guild(ctx.guild).seed_limit.set(limit)
        await ctx.send(f"✅ Maximum seed inventory set to **{limit}** per member. Existing inventories above the limit will not be deleted.")

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="setbloomtime", help="Set the minimum and maximum seed growing time in hours.")
    async def setbloomtime(self, ctx, min_hours: int, max_hours: int):
        if min_hours < 1 or max_hours < min_hours or max_hours > 168:
            return await ctx.send("⚠️ Use a range from 1 to 168 hours, with minimum no greater than maximum.")
        guild_conf = self.config.guild(ctx.guild)
        await guild_conf.min_bloom_hours.set(min_hours)
        await guild_conf.max_bloom_hours.set(max_hours)
        await ctx.send(f"✅ Growing time set to **{min_hours}–{max_hours} hours**.")

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="setrewardweights", help="Set reward probabilities. Example: setrewardweights currency:28,prompt:12,fortune:12,advice:12,flower:14,mystery:8,seed:6,xp:6,jackpot:2")
    async def setrewardweights(self, ctx, *, weights: str):
        parsed = {}
        try:
            for item in re.split(r"[,\s]+", weights.strip()):
                if not item:
                    continue
                if ":" in item:
                    key, value = item.split(":", 1)
                elif "=" in item:
                    key, value = item.split("=", 1)
                else:
                    raise ValueError
                key = key.lower().strip()
                if key not in DEFAULT_REWARD_WEIGHTS:
                    return await ctx.send(f"⚠️ Unknown reward type `{key}`. Valid types: {', '.join(DEFAULT_REWARD_WEIGHTS)}.")
                amount = float(value)
                if not math.isfinite(amount) or amount < 0 or amount > 100000:
                    raise ValueError
                parsed[key] = amount
        except ValueError:
            return await ctx.send("⚠️ Invalid format. Example: `currency:28,prompt:12,fortune:12,advice:12,flower:14,mystery:8,seed:6,xp:6,jackpot:2`.")
        current = await self.config.guild(ctx.guild).reward_weights()
        current.update(parsed)
        if sum(float(value) for value in current.values()) <= 0:
            return await ctx.send("⚠️ At least one reward type must have a weight greater than zero.")
        await self.config.guild(ctx.guild).reward_weights.set(current)
        await ctx.send("✅ Reward weights updated. Weights are relative probabilities, so they do not need to add up to 100.")

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="fortunechannel", help="Set the reward delivery channel. Run without a channel to reset to the planting channel.")
    async def fortunechannel(self, ctx, channel: discord.TextChannel = None):
        await self.config.guild(ctx.guild).reward_channel.set(channel.id if channel else None)
        await ctx.send(f"✅ Bloom rewards will be delivered in {channel.mention}." if channel else "✅ Bloom rewards will be delivered in the original planting channel, with DM fallback.")

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="fortuneignore", help="Toggle an ignored channel or role. Usage: fortuneignore channel #channel / fortuneignore role @role / fortuneignore list")
    async def fortuneignore(self, ctx, target_type: str = "list", target_id: str = None):
        guild_conf = self.config.guild(ctx.guild)
        kind = target_type.lower()
        if kind == "list":
            data = await guild_conf.all()
            channels = [ctx.guild.get_channel(int(value)) for value in data.get("ignored_channels", [])]
            roles = [ctx.guild.get_role(int(value)) for value in data.get("ignored_roles", [])]
            return await ctx.send("**Ignored channels:** " + (", ".join(channel.mention for channel in channels if channel) or "None") + "\n**Ignored roles:** " + (", ".join(role.mention for role in roles if role) or "None"))
        if kind not in ("channel", "role") or target_id is None:
            return await ctx.send("⚠️ Use `fortuneignore channel #channel`, `fortuneignore role @role`, or `fortuneignore list`.")
        match = re.search(r"\d{15,22}", target_id)
        if not match:
            return await ctx.send("⚠️ Provide a channel or role mention/ID.")
        object_id = int(match.group())
        if kind == "channel":
            target = ctx.guild.get_channel(object_id)
            if target is None:
                return await ctx.send("⚠️ That channel isn't part of this server.")
            value = await guild_conf.ignored_channels()
            label = target.mention
            config_value = guild_conf.ignored_channels
        else:
            target = ctx.guild.get_role(object_id)
            if target is None:
                return await ctx.send("⚠️ That role isn't part of this server.")
            value = await guild_conf.ignored_roles()
            label = target.mention
            config_value = guild_conf.ignored_roles
        value = [int(item) for item in value]
        if object_id in value:
            value.remove(object_id)
            state = "removed from"
        else:
            value.append(object_id)
            state = "added to"
        await config_value.set(value)
        await ctx.send(f"✅ {label} {state} the FortuneGarden ignore list.")

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="fortunereview", help="List bloom rewards whose currency payout needs manual review.")
    async def fortunereview(self, ctx):
        guild_data = await self.config.guild(ctx.guild).all()
        entries = []
        for fid, info in guild_data.get("fortunes", {}).items():
            if not info.get("currency_review"):
                continue
            amount = info.get("reward", {}).get("amount", 0)
            owner = ctx.guild.get_member(int(info.get("owner_id", 0)))
            owner_label = owner.mention if owner else f"User ID {info.get('owner_id', 'unknown')}"
            error = str(info.get("last_error", "Needs review"))[:200]
            entries.append(f"`{fid}` — {owner_label} — **{amount}** credits — {error}")
        if not entries:
            return await ctx.send("✅ There are no currency rewards awaiting manual review.")
        embed = discord.Embed(title="⚠️ FortuneGarden Payout Review", description="\n".join(entries)[:4000], color=discord.Color.orange())
        await ctx.send(embed=embed)

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="fortunereconcile", help="Resolve a currency payout flagged for review. Use 'paid' only after verifying the user already received it; use 'retry' only after verifying they did not.")
    async def fortunereconcile(self, ctx, fid: str, action: str):
        action = action.lower()
        if action not in ("paid", "retry"):
            return await ctx.send("⚠️ Use `fortunereconcile <seed_id> paid` or `fortunereconcile <seed_id> retry`.")
        guild_lock = self._guild_lock(ctx.guild.id)
        async with guild_lock:
            guild_conf = self.config.guild(ctx.guild)
            fortunes = await guild_conf.fortunes()
            info = fortunes.get(fid)
            if not info or not info.get("currency_review"):
                return await ctx.send("That seed does not have a currency payout awaiting review.")
            if action == "paid":
                info["currency_claimed"] = True
                info["currency_applied"] = True
            else:
                info["currency_claimed"] = False
                info["currency_applied"] = False
            info.pop("currency_review", None)
            info.pop("last_error", None)
            await guild_conf.fortunes.set(fortunes)
        await ctx.send("✅ Payout marked as already paid. The bloom will continue to delivery." if action == "paid" else "✅ Payout claim cleared. The bloom processor may retry the deposit.")

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="fortuneadmin", help="Inspect or manage a member's garden. Actions: inspect, addseeds, removeseeds, addxp, addcredits.")
    async def fortuneadmin(self, ctx, member: discord.Member, action: str = "inspect", amount: int = 1):
        action = action.lower()
        lock = self._member_lock(ctx.guild.id, member.id)
        async with lock:
            member_conf = self.config.member(member)
            garden = await self._get_garden(member_conf)
            if action == "inspect":
                pass
            elif action in ("addseeds", "removeseeds"):
                if amount < 1 or amount > 1000:
                    return await ctx.send("⚠️ Amount must be between 1 and 1,000.")
                if action == "addseeds":
                    garden["seed_inventory"]["common"] = garden["seed_inventory"].get("common", 0) + amount
                else:
                    remove = min(amount, garden["seeds"])
                    for seed_type in ("common", "golden", "moonlight", "ancient"):
                        available = garden["seed_inventory"].get(seed_type, 0)
                        taken = min(available, remove)
                        garden["seed_inventory"][seed_type] = available - taken
                        remove -= taken
                        if remove <= 0:
                            break
                await self._save_garden(member_conf, garden)
            elif action == "addcredits":
                if amount < 1 or amount > 1000000000:
                    return await ctx.send("⚠️ Credit amount must be between 1 and 1,000,000,000.")
                await bank.deposit_credits(member, amount)
            elif action == "addxp":
                if amount < 1 or amount > 100000:
                    return await ctx.send("⚠️ XP amount must be between 1 and 100,000.")
                self._add_xp(garden, amount)
                achievements = self._check_achievements(garden)
                await self._save_garden(member_conf, garden)
            else:
                return await ctx.send("⚠️ Actions: `inspect`, `addseeds`, `removeseeds`, `addxp`, `addcredits`.")
        if action == "inspect":
            await ctx.send(f"**{member}** — Level {garden['garden_level']} • {garden['garden_xp']} XP • {garden['seeds']} seeds • {garden['total_blooms']} blooms • {len(garden['flowers'])} unique flowers • {len(garden['achievements'])} achievements.")
        elif action in ("addseeds", "removeseeds"):
            await ctx.send(f"✅ Updated {member.mention}'s seed inventory. They now have **{garden['seeds']}** seeds.")
        elif action == "addcredits":
            currency = await bank.get_currency_name(ctx.guild)
            await ctx.send(f"✅ Deposited **{amount} {currency}** into {member.mention}'s balance. Check `fortunereview` before manually resolving an interrupted payout to avoid duplicate credits.")
        else:
            await ctx.send(f"✅ Added **{amount} XP** to {member.mention}'s garden." + (f"\n🏅 Unlocked: {', '.join(achievements)}" if achievements else ""))


async def setup(bot):
    await bot.add_cog(FortuneGarden(bot))
