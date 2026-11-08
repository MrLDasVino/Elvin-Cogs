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
    "Use `{prefix}forgarden` to open your garden and plant one!"
)

SEED_BANNER = "https://files.catbox.moe/eayj32.png"
PLANT_BANNER = "https://files.catbox.moe/wvf27j.png"
LIST_BANNER = "https://files.catbox.moe/rn4git.png"
REWARD_BANNERS = {
    "currency": "https://files.catbox.moe/qc1h6u.png",
    "jackpot": "https://files.catbox.moe/qc1h6u.png",
    "prompt": "https://files.catbox.moe/q04tqy.png",
    "fortune": "https://files.catbox.moe/4jbpxq.png",
    "advice": "https://files.catbox.moe/1gs6jr.png",
    "flower": PLANT_BANNER,
    "seed": SEED_BANNER,
    "mystery": PLANT_BANNER,
    "xp": LIST_BANNER,
    "fertilizer": PLANT_BANNER,
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
    "Sunpetal": "Common",
    "Snowdrop": "Common",
    "Honeybell": "Uncommon",
    "Lavender": "Uncommon",
    "Foxglove": "Uncommon",
    "Silver Fern": "Uncommon",
    "Amberleaf": "Uncommon",
    "Nightshade Bell": "Uncommon",
    "Moonflower": "Uncommon",
    "Crystal Rose": "Rare",
    "Star Lily": "Rare",
    "Firefly Orchid": "Rare",
    "Glacier Peony": "Rare",
    "Ruins Orchid": "Rare",
    "Dreamrose": "Rare",
    "Rainkissed Iris": "Rare",
    "Dragonfruit Bloom": "Rare",
    "Celestial Lily": "Epic",
    "Aurora Bloom": "Epic",
    "Nebula Rose": "Epic",
    "Comet Blossom": "Epic",
    "Prism Poppy": "Epic",
    "Stormglass Iris": "Epic",
    "Verdant Crown": "Epic",
    "Emberheart Bloom": "Epic",
    "Eternal Blossom": "Legendary",
    "Ghost Orchid": "Legendary",
    "Starfall Peony": "Legendary",
    "Elderlight Blossom": "Legendary",
    "Cinder Lily": "Rare",
    "Tideglass Lotus": "Rare",
    "Deepsea Anemone": "Uncommon",
    "Frostbell": "Seasonal",
    "Sakura": "Seasonal",
    "Sunflare": "Seasonal",
    "Harvest Crown": "Seasonal",
    "Springtide Bellflower": "Seasonal",
    "Ember Tulip": "Seasonal",
}
BIOME_FLOWERS = {
    "meadow": ["Dandelion", "Clover", "Daisy", "Bluebell", "Sunpetal", "Honeybell", "Amberleaf"],
    "moonlit": ["Moonflower", "Star Lily", "Firefly Orchid", "Dreamrose", "Nightshade Bell", "Ghost Orchid"],
    "frozen": ["Frostbell", "Glacier Peony", "Bluebell", "Snowdrop", "Aurora Bloom", "Ember Tulip"],
    "celestial": ["Celestial Lily", "Aurora Bloom", "Nebula Rose", "Comet Blossom", "Starfall Peony", "Prism Poppy"],
    "ruins": ["Ruins Orchid", "Silver Fern", "Foxglove", "Dragonfruit Bloom", "Ghost Orchid", "Stormglass Iris", "Elderlight Blossom"],
    "enchanted": ["Honeybell", "Verdant Crown", "Elderlight Blossom", "Dreamrose", "Foxglove", "Sunpetal"],
    "volcanic": ["Cinder Lily", "Emberheart Bloom", "Sunflare", "Dragonfruit Bloom", "Stormglass Iris"],
    "tidal": ["Tideglass Lotus", "Deepsea Anemone", "Rainkissed Iris", "Bluebell", "Moonflower"],
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
    16: "Moonwell Fountain",
    20: "Ancient Rune Circle",
    25: "Enchanted Treehouse",
    30: "Emberglass Conservatory",
    35: "Tideglass Pavilion",
}
ACHIEVEMENT_DESCRIPTIONS = {
    "First Plant": "Plant your first fortune seed.",
    "First Bloom": "Receive your first bloom.",
    "Dedicated Gardener": "Grow 10 seeds.",
    "Master Gardener": "Grow 50 seeds.",
    "Evergreen Heart": "Grow 100 seeds.",
    "Seed Sower": "Plant 10 seeds.",
    "Seed Artisan": "Plant 50 seeds.",
    "Seed Legend": "Plant 100 seeds.",
    "Green Thumb": "Reach garden level 5.",
    "Verdant Master": "Reach garden level 10.",
    "Garden Legend": "Reach garden level 25.",
    "Botanist": "Collect 5 different flowers.",
    "Collector's Pride": "Collect 10 different flowers.",
    "Living Herbarium": "Collect 20 different flowers.",
    "Bouquet Maker": "Collect 50 flowers in total.",
    "Rare Discovery": "Discover a Rare flower.",
    "Beyond the Ordinary": "Discover an Epic flower.",
    "Once in a Lifetime": "Discover a Legendary flower.",
    "Faithful Waterer": "Reach a seven-day watering streak.",
    "Rainkeeper": "Reach a fourteen-day watering streak.",
    "Water Bearer": "Water 100 growing seeds over time.",
    "Alchemist's Apprentice": "Craft your first potion.",
    "Master Alchemist": "Craft 10 potions.",
    "Grand Alchemist": "Craft 50 potions.",
    "First Expedition": "Complete your first expedition.",
    "Pathfinder": "Complete 10 expeditions.",
    "World Wanderer": "Complete 25 expeditions.",
    "Friendly Face": "Visit 5 other gardens.",
    "Garden Ambassador": "Visit 25 other gardens.",
    "Beloved Garden": "Receive 10 garden visits.",
    "Generous Gardener": "Gift 10 flowers to other gardeners.",
    "Fair Trader": "Complete 5 player trades.",
    "Festival Friend": "Earn 5 seasonal or festival bloom points.",
    "Festival Legend": "Earn 30 seasonal or festival bloom points.",
    "Companion Keeper": "Discover 3 garden companions.",
    "Menagerie": "Discover every garden companion.",
    "Biome Explorer": "Unlock 3 garden biomes.",
    "World Traveller": "Unlock every garden biome.",
    "Decorative Touch": "Unlock 5 garden decorations.",
    "Quest Collector": "Claim 10 daily or weekly quests.",
    "Community Roots": "Contribute 250 points to a community garden.",
    "Heart of the Village": "Contribute 1,000 points to a community garden.",
    "World Tree Keeper": "Grow your World Tree to level 10.",
    "Prestigious": "Reach your first garden prestige.",
    "Fivefold Prestige": "Reach garden prestige 5.",
    "Weather Watcher": "Experience 6 different kinds of garden weather.",
    "Market Regular": "Buy 10 items from the garden market.",
    "Master Explorer": "Complete 50 expeditions.",
    "Seasonal Collector": "Collect 4 different seasonal flowers.",
    "Moon Phase Scholar": "Plant seeds under all 8 moon phases.",
    "Garden Archivist": "Record 20 bloom rewards in your history.",
    "Grand Host": "Welcome 50 visitors to your garden.",
}
ACHIEVEMENT_REWARDS = {
    "First Plant": {"xp": 20, "seeds": {"common": 1}},
    "First Bloom": {"xp": 25, "items": {"fertilizer": 1}},
    "Dedicated Gardener": {"xp": 50, "seeds": {"common": 2}},
    "Master Gardener": {"xp": 100, "seeds": {"golden": 1}},
    "Evergreen Heart": {"xp": 200, "seeds": {"moonlight": 1}},
    "Seed Sower": {"xp": 35, "items": {"fertilizer": 1}},
    "Seed Artisan": {"xp": 75, "potions": {"growth_potion": 1}},
    "Seed Legend": {"xp": 150, "seeds": {"golden": 2}},
    "Green Thumb": {"xp": 50, "items": {"fertilizer": 2}},
    "Verdant Master": {"xp": 100, "potions": {"fortune_elixir": 1}},
    "Garden Legend": {"xp": 250, "seeds": {"ancient": 1}},
    "Botanist": {"xp": 40, "items": {"fertilizer": 1}},
    "Collector's Pride": {"xp": 80, "potions": {"golden_fertilizer": 1}},
    "Living Herbarium": {"xp": 160, "seeds": {"moonlight": 1}},
    "Bouquet Maker": {"xp": 75, "potions": {"nectar_tonic": 1}},
    "Rare Discovery": {"xp": 50, "items": {"fertilizer": 1}},
    "Beyond the Ordinary": {"xp": 100, "potions": {"aurora_draught": 1}},
    "Once in a Lifetime": {"xp": 250, "seeds": {"ancient": 1}},
    "Faithful Waterer": {"xp": 75, "items": {"fertilizer": 2}},
    "Rainkeeper": {"xp": 150, "potions": {"dew_of_renewal": 1}},
    "Water Bearer": {"xp": 180, "potions": {"golden_fertilizer": 2}},
    "Alchemist's Apprentice": {"xp": 35, "potions": {"growth_potion": 1}},
    "Master Alchemist": {"xp": 100, "potions": {"fortune_elixir": 1}},
    "Grand Alchemist": {"xp": 250, "seeds": {"golden": 1}},
    "First Expedition": {"xp": 40, "items": {"fertilizer": 1}},
    "Pathfinder": {"xp": 100, "seeds": {"moonlight": 1}},
    "World Wanderer": {"xp": 200, "seeds": {"ancient": 1}},
    "Friendly Face": {"xp": 40, "items": {"fertilizer": 1}},
    "Garden Ambassador": {"xp": 100, "potions": {"pollinator_charm": 1}},
    "Beloved Garden": {"xp": 100, "seeds": {"golden": 1}},
    "Generous Gardener": {"xp": 100, "potions": {"nectar_tonic": 1}},
    "Fair Trader": {"xp": 100, "seeds": {"golden": 1}},
    "Festival Friend": {"xp": 60, "items": {"fertilizer": 2}},
    "Festival Legend": {"xp": 180, "seeds": {"moonlight": 1}},
    "Companion Keeper": {"xp": 75, "potions": {"rootbound_brew": 1}},
    "Menagerie": {"xp": 200, "seeds": {"ancient": 1}},
    "Biome Explorer": {"xp": 75, "potions": {"aurora_draught": 1}},
    "World Traveller": {"xp": 200, "seeds": {"ancient": 1}},
    "Decorative Touch": {"xp": 75, "items": {"fertilizer": 2}},
    "Quest Collector": {"xp": 100, "potions": {"fortune_elixir": 1}},
    "Community Roots": {"xp": 75, "seeds": {"golden": 1}},
    "Heart of the Village": {"xp": 200, "seeds": {"ancient": 1}},
    "World Tree Keeper": {"xp": 150, "potions": {"rootbound_brew": 1}},
    "Prestigious": {"xp": 100, "seeds": {"ancient": 1}},
    "Fivefold Prestige": {"xp": 300, "potions": {"prism_philter": 2}},
    "Weather Watcher": {"xp": 75, "potions": {"stargazer_serum": 1}},
    "Market Regular": {"xp": 50, "items": {"fertilizer": 2}},
    "Master Explorer": {"xp": 300, "seeds": {"ancient": 1}},
    "Seasonal Collector": {"xp": 120, "potions": {"sunfire_syrup": 1}},
    "Moon Phase Scholar": {"xp": 180, "potions": {"moonlight_essence": 2}},
    "Garden Archivist": {"xp": 100, "potions": {"dreamweaver_elixir": 1}},
    "Grand Host": {"xp": 200, "seeds": {"golden": 1}},
}


# Additional FortuneGarden systems
COMPANIONS = {
    "fairy": {"label": "Garden Fairy", "emoji": "🧚", "description": "Improves the chance of finding rarer flowers.", "cost": {"flower": "Moonflower", "count": 2}},
    "fox": {"label": "Clover Fox", "emoji": "🦊", "description": "Shortens growing times by 5%.", "cost": {"flower": "Clover", "count": 3}},
    "owl": {"label": "Wisdom Owl", "emoji": "🦉", "description": "Grants 10% more garden experience.", "cost": {"flower": "Bluebell", "count": 3}},
    "firefly": {"label": "Moonfire Firefly", "emoji": "✨", "description": "Shortens growing times by 10%.", "cost": {"flower": "Lavender", "count": 2}},
    "spirit": {"label": "Ancient Forest Spirit", "emoji": "🌳", "description": "Improves rare finds and expedition rewards.", "cost": {"flower": "Star Lily", "count": 1}},
    "bee": {"label": "Honeybee Familiar", "emoji": "🐝", "description": "Improves uncommon and rare flower discoveries.", "cost": {"flower": "Honeybell", "count": 3}},
    "turtle": {"label": "Mossback Turtle", "emoji": "🐢", "description": "Reduces growing times by 8%.", "cost": {"flower": "Silver Fern", "count": 2}},
    "phoenix": {"label": "Ember Phoenix", "emoji": "🔥", "description": "Grants 15% more garden XP from blooms.", "cost": {"flower": "Emberheart Bloom", "count": 1}},
    "dragon": {"label": "Gilded Dragonling", "emoji": "🐉", "description": "Improves the chance of a flower or jackpot reward.", "cost": {"flower": "Dragonfruit Bloom", "count": 2}},
    "koi": {"label": "Moonpool Koi", "emoji": "🐟", "description": "Seeds grow 10% faster on rainy days and moonlit nights.", "cost": {"flower": "Tideglass Lotus", "count": 1}},
}
BIOMES = {
    "meadow": {"label": "Wildflower Meadow", "level": 1, "description": "A gentle green starting garden."},
    "moonlit": {"label": "Moonlit Garden", "level": 5, "description": "A silver garden beneath a permanent twilight."},
    "frozen": {"label": "Frostbound Sanctuary", "level": 10, "description": "A quiet garden of snow and crystal."},
    "celestial": {"label": "Celestial Garden", "level": 15, "description": "A garden among the stars."},
    "ruins": {"label": "Ancient Ruins", "level": 20, "description": "An overgrown sanctuary from a forgotten age."},
    "enchanted": {"label": "Whispering Enclave", "level": 25, "description": "A woodland where the leaves remember every story ever told."},
    "volcanic": {"label": "Emberwild Crater", "level": 30, "description": "A warm volcanic garden where fire-resistant flowers thrive."},
    "tidal": {"label": "Tideglass Sanctuary", "level": 35, "description": "A submerged garden illuminated by drifting sea-glass lights."},
}
DESIGN_OPTIONS = {
    "layout": {"cottage": "Cottage", "formal": "Formal", "wild": "Wild", "zen": "Zen"},
    "background": {"sunrise": "Sunrise", "emerald": "Emerald", "twilight": "Twilight", "starlight": "Starlight"},
    "path": {"stone": "Stone", "moss": "Moss", "crystal": "Crystal", "wood": "Wood"},
}
RECIPES = {
    "growth_potion": {"label": "Growth Potion", "ingredients": {"Dandelion": 2, "Clover": 1}, "description": "Reduces a growing seed's timer by two hours."},
    "golden_fertilizer": {"label": "Golden Fertilizer", "ingredients": {"Moonflower": 1, "Lavender": 2}, "description": "Fertilizes a seed and improves its flower rarity."},
    "fortune_elixir": {"label": "Fortune Elixir", "ingredients": {"Daisy": 2, "Crystal Rose": 1}, "description": "Improves the next bloom's chance of a flower or jackpot reward."},
    "moonlight_essence": {"label": "Moonlight Essence", "ingredients": {"Moonflower": 2, "Star Lily": 1}, "description": "Improves the next bloom's moonlit flower chances and growth speed."},
    "nectar_tonic": {"label": "Nectar Tonic", "ingredients": {"Honeybell": 2, "Lavender": 1}, "description": "Adds a generous experience bonus to the next bloom."},
    "pollinator_charm": {"label": "Pollinator Charm", "ingredients": {"Clover": 2, "Firefly Orchid": 1}, "description": "Guarantees a flower reward from the next bloom."},
    "dew_of_renewal": {"label": "Dew of Renewal", "ingredients": {"Rainkissed Iris": 2, "Daisy": 1}, "description": "Reduces a growing seed's timer by four hours."},
    "aurora_draught": {"label": "Aurora Draught", "ingredients": {"Aurora Bloom": 1, "Frostbell": 1, "Star Lily": 1}, "description": "Fertilizes a seed and gives it an extra chance at rare flowers."},
    "rootbound_brew": {"label": "Rootbound Brew", "ingredients": {"Silver Fern": 2, "Ruins Orchid": 1}, "description": "Grants a large garden XP bonus when the seed blooms."},
    "sunfire_syrup": {"label": "Sunfire Syrup", "ingredients": {"Sunpetal": 2, "Sunflare": 1}, "description": "Increases the next currency or jackpot reward by 35%."},
    "prism_philter": {"label": "Prism Philter", "ingredients": {"Prism Poppy": 1, "Crystal Rose": 1}, "description": "Greatly improves the next bloom's fortune and flower chances."},
    "dreamweaver_elixir": {"label": "Dreamweaver Elixir", "ingredients": {"Dreamrose": 1, "Moonflower": 1, "Nightshade Bell": 1}, "description": "Guarantees a writing prompt reward from the next bloom."},
    "stargazer_serum": {"label": "Stargazer Serum", "ingredients": {"Comet Blossom": 1, "Nebula Rose": 1}, "description": "Adds bonus XP and a chance of an extra flower to the next bloom."},
}
EXPEDITIONS = {
    "whispering_woods": {"label": "Whispering Woods", "hours": 1, "description": "A short journey through an ancient forest."},
    "forgotten_ruins": {"label": "Forgotten Ruins", "hours": 3, "description": "Search a lost sanctuary for rare treasures."},
    "crystal_caverns": {"label": "Crystal Caverns", "hours": 2, "description": "Mine sparkling crystals and magical fertilizer."},
    "moonlit_lake": {"label": "Moonlit Lake", "hours": 2, "description": "Explore a lake that reflects the stars."},
    "ember_citadel": {"label": "Ember Citadel", "hours": 4, "description": "Search a volcanic fortress for heat-born flowers and treasures."},
    "sunken_grotto": {"label": "Sunken Grotto", "hours": 3, "description": "Dive into a hidden underwater garden of glassy petals."},
    "dreamwood": {"label": "Dreamwood", "hours": 5, "description": "Follow a drifting dream-path through a forest that changes at dusk."},
}
MARKET_ITEMS = {
    "fertilizer": {"label": "Fertilizer", "price": 80, "description": "Speeds up a seed and improves flower odds."},
    "growth_potion": {"label": "Growth Potion", "price": 180, "description": "Reduces one seed's timer by two hours."},
    "fortune_elixir": {"label": "Fortune Elixir", "price": 220, "description": "Improves the next bloom's bonus rewards."},
    "common_seed": {"label": "Common Seed", "price": 120, "description": "A reliable seed for your garden."},
    "golden_seed": {"label": "Golden Seed", "price": 450, "description": "A valuable seed with improved reward odds."},
    "nectar_tonic": {"label": "Nectar Tonic", "price": 260, "description": "Adds bonus garden XP to the next bloom."},
    "pollinator_charm": {"label": "Pollinator Charm", "price": 340, "description": "Guarantees a flower reward on the next bloom."},
    "dew_of_renewal": {"label": "Dew of Renewal", "price": 300, "description": "Reduces one seed's timer by four hours."},
    "aurora_draught": {"label": "Aurora Draught", "price": 520, "description": "Improves the next seed's rare flower chances."},
    "rootbound_brew": {"label": "Rootbound Brew", "price": 400, "description": "Adds a large XP reward to the next bloom."},
    "sunfire_syrup": {"label": "Sunfire Syrup", "price": 380, "description": "Boosts the next currency reward."},
    "prism_philter": {"label": "Prism Philter", "price": 600, "description": "Improves the next bloom's fortune."},
    "dreamweaver_elixir": {"label": "Dreamweaver Elixir", "price": 320, "description": "Guarantees a writing prompt on the next bloom."},
    "stargazer_serum": {"label": "Stargazer Serum", "price": 480, "description": "Adds XP and a chance of an extra flower."},
}
DAILY_QUEST_POOL = [
    {"id": "plant", "description": "Plant 2 seeds", "target": 2, "xp": 35, "item": "fertilizer", "amount": 1},
    {"id": "water", "description": "Water 1 seed", "target": 1, "xp": 25, "item": "fertilizer", "amount": 1},
    {"id": "bloom", "description": "Bloom 1 seed", "target": 1, "xp": 40, "item": "common_seed", "amount": 1},
    {"id": "flower", "description": "Discover 1 flower", "target": 1, "xp": 35, "item": "fertilizer", "amount": 1},
    {"id": "visit", "description": "Visit 1 garden", "target": 1, "xp": 25, "item": "common_seed", "amount": 1},
    {"id": "expedition", "description": "Complete 1 expedition", "target": 1, "xp": 45, "item": "fertilizer", "amount": 1},
    {"id": "craft", "description": "Craft 1 alchemy item", "target": 1, "xp": 40, "item": "growth_potion", "amount": 1},
    {"id": "community", "description": "Contribute to the community garden", "target": 1, "xp": 35, "item": "fertilizer", "amount": 1},
    {"id": "gift", "description": "Gift a flower to another gardener", "target": 1, "xp": 35, "item": "common_seed", "amount": 1},
    {"id": "festival", "description": "Bloom 1 seed during this week's festival", "target": 1, "xp": 35, "item": "fortune_elixir", "amount": 1},
]
WEEKLY_QUEST_POOL = [
    {"id": "plant", "description": "Plant 10 seeds", "target": 10, "xp": 150, "item": "golden_seed", "amount": 1},
    {"id": "water", "description": "Water 5 seeds", "target": 5, "xp": 120, "item": "fertilizer", "amount": 4},
    {"id": "bloom", "description": "Bloom 8 seeds", "target": 8, "xp": 180, "item": "golden_seed", "amount": 1},
    {"id": "flower", "description": "Discover 5 flowers", "target": 5, "xp": 160, "item": "fortune_elixir", "amount": 1},
    {"id": "visit", "description": "Visit 5 gardens", "target": 5, "xp": 120, "item": "growth_potion", "amount": 1},
    {"id": "expedition", "description": "Complete 4 expeditions", "target": 4, "xp": 180, "item": "golden_seed", "amount": 1},
    {"id": "craft", "description": "Craft 2 alchemy items", "target": 2, "xp": 140, "item": "fertilizer", "amount": 3},
    {"id": "community", "description": "Contribute 5 times to the community garden", "target": 5, "xp": 160, "item": "aurora_draught", "amount": 1},
    {"id": "gift", "description": "Gift 3 flowers to other gardeners", "target": 3, "xp": 150, "item": "nectar_tonic", "amount": 1},
    {"id": "trade", "description": "Complete 2 player trades", "target": 2, "xp": 150, "item": "golden_seed", "amount": 1},
    {"id": "festival", "description": "Bloom 10 seeds during weekly festivals", "target": 10, "xp": 200, "item": "stargazer_serum", "amount": 1},
]

FESTIVAL_EVENTS = {
    "firefly_nights": {"name": "Firefly Nights", "flower": "Firefly Orchid", "emoji": "✨", "description": "Follow tiny lights through the midnight garden."},
    "rain_dance": {"name": "Rain Dance Week", "flower": "Rainkissed Iris", "emoji": "🌧️", "description": "Celebrate the nourishing summer rain."},
    "stargazer_week": {"name": "Stargazer Week", "flower": "Comet Blossom", "emoji": "☄️", "description": "Watch the skies for rare celestial petals."},
    "pollinator_parade": {"name": "Pollinator Parade", "flower": "Honeybell", "emoji": "🐝", "description": "Welcome bees, butterflies and busy little helpers."},
    "dream_tide": {"name": "Dream Tide", "flower": "Dreamrose", "emoji": "🌙", "description": "Collect flowers touched by sleeping dreams."},
    "crystal_week": {"name": "Crystal Bloom Week", "flower": "Crystal Rose", "emoji": "💎", "description": "The garden crystals are humming with energy."},
    "aurora_festival": {"name": "Aurora Festival", "flower": "Aurora Bloom", "emoji": "🌌", "description": "A ribbon of aurora light awakens rare blossoms."},
    "ancient_echoes": {"name": "Ancient Echoes", "flower": "Ghost Orchid", "emoji": "🏛️", "description": "Forgotten seeds whisper beneath the old ruins."},
}

WEATHER_EFFECTS = {
    "Sunny": {"description": "Seeds grow 5% faster. Sunpetals may appear in the bloom.", "growth_multiplier": 0.95, "flower_bonus": 1.0, "xp_bonus": 0, "special_flower": "Sunpetal", "special_chance": 0.08},
    "Rainy": {"description": "Seeds grow 10% faster. Rainkissed Irises may appear, and a little fertilizer can wash into the garden.", "growth_multiplier": 0.90, "flower_bonus": 1.04, "xp_bonus": 2, "special_flower": "Rainkissed Iris", "special_chance": 0.10, "bonus_fertilizer_chance": 0.05},
    "Foggy": {"description": "Rare and better flowers are slightly more likely.", "growth_multiplier": 1.02, "flower_bonus": 1.18, "xp_bonus": 0, "special_flower": "Ghost Orchid", "special_chance": 0.025},
    "Breezy": {"description": "Seeds grow 4% faster and common blooms are lively.", "growth_multiplier": 0.96, "flower_bonus": 1.03, "xp_bonus": 0},
    "Starry": {"description": "Moonlight seeds grow 12% faster and Comet Blossoms may appear.", "growth_multiplier": 1.0, "moonlight_multiplier": 0.88, "flower_bonus": 1.10, "xp_bonus": 3, "special_flower": "Comet Blossom", "special_chance": 0.08},
    "Overcast": {"description": "A calm day with no special growing effect.", "growth_multiplier": 1.0, "flower_bonus": 1.0, "xp_bonus": 0},
    "Thunderstorm": {"description": "Seeds take 5% longer, but blooms grant 12 bonus XP, may reveal Stormglass Irises and can uncover fertilizer.", "growth_multiplier": 1.05, "flower_bonus": 1.10, "xp_bonus": 12, "special_flower": "Stormglass Iris", "special_chance": 0.07, "bonus_fertilizer_chance": 0.12},
    "Rainbow": {"description": "Seeds grow 8% faster and flower rarity improves.", "growth_multiplier": 0.92, "flower_bonus": 1.22, "xp_bonus": 5, "special_flower": "Prism Poppy", "special_chance": 0.08},
    "Blossom Rain": {"description": "Seeds grow 10% faster and seasonal blossoms are more likely.", "growth_multiplier": 0.90, "flower_bonus": 1.12, "xp_bonus": 4, "special_flower": "Springtide Bellflower", "special_chance": 0.08},
    "Meteor Shower": {"description": "Moonlight seeds grow 15% faster and Comet Blossoms may be found.", "growth_multiplier": 1.0, "moonlight_multiplier": 0.85, "flower_bonus": 1.16, "xp_bonus": 8, "special_flower": "Comet Blossom", "special_chance": 0.12},
    "Aurora": {"description": "Rare flower chances improve and Aurora Blooms may appear.", "growth_multiplier": 0.98, "flower_bonus": 1.24, "xp_bonus": 6, "special_flower": "Aurora Bloom", "special_chance": 0.10},
    "Drought": {"description": "Seeds grow 10% slower, but Sunflare blooms are more likely.", "growth_multiplier": 1.10, "flower_bonus": 1.08, "xp_bonus": 0, "special_flower": "Sunflare", "special_chance": 0.08},
    "Snowy": {"description": "Seeds grow 5% slower. Frostbells and Snowdrops may appear.", "growth_multiplier": 1.05, "flower_bonus": 1.08, "xp_bonus": 2, "special_flower": "Frostbell", "special_chance": 0.10},
    "Starlit": {"description": "Moonlight seeds grow 5% faster and celestial flowers are more likely.", "growth_multiplier": 1.0, "moonlight_multiplier": 0.95, "flower_bonus": 1.15, "xp_bonus": 5, "special_flower": "Starfall Peony", "special_chance": 0.025},
    "Ashfall": {"description": "Seeds take 5% longer, but Emberheart Blooms and Cinder Lilies may emerge. Blooms grant 8 bonus XP.", "growth_multiplier": 1.05, "flower_bonus": 1.12, "xp_bonus": 8, "special_flower": "Cinder Lily", "special_chance": 0.12},
    "High Tide": {"description": "Seeds grow 5% faster and Tideglass Lotuses may be discovered.", "growth_multiplier": 0.95, "flower_bonus": 1.10, "xp_bonus": 4, "special_flower": "Tideglass Lotus", "special_chance": 0.12},
    "Sea Mist": {"description": "Rare flowers are more likely to appear in the cool sea mist.", "growth_multiplier": 1.02, "flower_bonus": 1.20, "xp_bonus": 3, "special_flower": "Deepsea Anemone", "special_chance": 0.10},
}



def quest_periods(now=None):
    now = now or datetime.utcnow()
    daily_key = now.date().isoformat()
    iso = now.isocalendar()
    weekly_key = f"{iso.year}-W{iso.week:02d}"
    return daily_key, weekly_key


def weather_and_moon(now=None, biome="meadow"):
    now = now or datetime.utcnow()
    epoch = datetime(2000, 1, 6)
    days = (now.date() - epoch.date()).days
    lunar = (days % 29.530588) / 29.530588
    phases = ["New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous", "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent"]
    phase = phases[int((lunar * 8) + 0.5) % 8]
    weather_names = ["Sunny", "Rainy", "Foggy", "Breezy", "Starry", "Overcast", "Thunderstorm", "Rainbow", "Blossom Rain", "Meteor Shower", "Aurora", "Drought"]
    weights = [15, 14, 8, 10, 8, 10, 5, 3, 5, 4, 3, 5]
    if biome == "frozen":
        weather_names.extend(["Snowy", "Aurora"])
        weights.extend([8, 4])
    elif biome == "celestial":
        weather_names.extend(["Starlit", "Meteor Shower", "Aurora"])
        weights.extend([8, 6, 5])
    elif biome == "moonlit":
        weather_names.extend(["Starlit", "Foggy"])
        weights.extend([5, 4])
    elif biome == "volcanic":
        weather_names.extend(["Ashfall", "Thunderstorm"])
        weights.extend([9, 4])
    elif biome == "tidal":
        weather_names.extend(["High Tide", "Sea Mist"])
        weights.extend([8, 6])
    rng = random.Random(f"{now.date().isoformat()}:{biome}")
    weather = rng.choices(weather_names, weights=weights, k=1)[0]
    if biome == "celestial" and phase in ("New Moon", "Full Moon") and rng.random() < 0.5:
        weather = "Starlit"
    if biome == "frozen" and weather == "Rainy":
        weather = "Snowy"
    return weather, phase


def current_festival_event(now=None):
    now = now or datetime.utcnow()
    iso = now.isocalendar()
    keys = list(FESTIVAL_EVENTS)
    key = keys[(iso.week - 1) % len(keys)]
    event = dict(FESTIVAL_EVENTS[key])
    event["key"] = f"{iso.year}-W{iso.week:02d}-{key}"
    event["festival"] = key
    event["week"] = iso.week
    return event


def create_garden(seed_count=0):
    return {
        "seeds": max(0, int(seed_count)),
        "seed_inventory": {"common": max(0, int(seed_count)), "golden": 0, "moonlight": 0, "ancient": 0},
        "flowers": {},
        "garden_xp": 0,
        "garden_level": 1,
        "total_planted": 0,
        "total_blooms": 0,
        "total_waterings": 0,
        "total_crafted": 0,
        "total_expeditions": 0,
        "total_visits_made": 0,
        "total_trades_completed": 0,
        "total_gifts_sent": 0,
        "total_quests_claimed": 0,
        "total_community_points": 0,
        "total_items_purchased": 0,
        "event_blooms_total": 0,
        "festival_blooms_total": 0,
        "festival_history": [],
        "weather_seen": [],
        "moon_phases_seen": [],
        "reward_history": [],
        "achievements": [],
        "items": {"fertilizer": 0},
        "applied_reward_ids": [],
        "daily_water_date": None,
        "water_streak": 0,
        "last_water_date": None,
        "event_progress": {},
        "event_claims": [],
        "festival_progress": {},
        "festival_claims": [],
        "unlocked_decorations": [],
        "equipped_decoration": None,
        "companions": [],
        "equipped_companion": None,
        "biomes": ["meadow"],
        "equipped_biome": "meadow",
        "expedition": None,
        "quest_state": {},
        "world_tree_xp": 0,
        "world_tree_level": 1,
        "prestige": 0,
        "permanent_xp_bonus": 0,
        "community_claims": {},
        "guestbook": [],
        "visit_count": 0,
        "last_visit_gifts": {},
        "last_guestbook_posts": {},
        "birthday": None,
        "birthday_claimed_year": None,
        "design": {"layout": "cottage", "background": "emerald", "path": "stone"},
        "potions": {key: 0 for key in RECIPES},
        "active_boosts": {},
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
        super().__init__(timeout=300)
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


class GardenInteractionContext:
    def __init__(self, interaction, ephemeral=True):
        self.interaction = interaction
        self.ephemeral = ephemeral
        self.author = interaction.user
        self.guild = interaction.guild
        self.channel = interaction.channel
        self.bot = interaction.client

    async def send(self, content=None, **kwargs):
        kwargs.pop("ephemeral", None)
        kwargs["ephemeral"] = self.ephemeral
        if self.interaction.response.is_done():
            kwargs.setdefault("wait", True)
            return await self.interaction.followup.send(content, **kwargs)
        await self.interaction.response.send_message(content, **kwargs)
        if kwargs.get("view") is not None:
            try:
                return await self.interaction.original_response()
            except discord.HTTPException:
                return None
        return None


class GardenActionModal(discord.ui.Modal):
    def __init__(self, author_id, title, fields, handler):
        super().__init__(title=title[:45], timeout=300)
        self.author_id = author_id
        self.handler = handler
        for custom_id, label, placeholder, required in fields:
            self.add_item(discord.ui.TextInput(
                custom_id=custom_id,
                label=label[:45],
                placeholder=(placeholder or "")[:100],
                required=required,
                max_length=300 if custom_id in ("compliment", "message") else 100,
            ))

    async def on_submit(self, interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("This form belongs to someone else.", ephemeral=True)
        values = {item.custom_id: str(item.value).strip() for item in self.children}
        await self.handler(interaction, values)


class GardenMenuView(discord.ui.View):
    SECTIONS = {
        "home": ("🌿 FortuneGarden", "Choose a section below to manage your garden. Only the person who opened this menu can use its buttons; they expire after five minutes."),
        "garden": ("🏡 Your Garden", "View your garden, weather, World Tree, birthday rewards and prestige."),
        "seeds": ("🌱 Seeds & Growing", "Plant seeds, check your growing plants, and care for them."),
        "collections": ("📚 Collections", "Browse flowers, achievements, your botanical journal and reward history."),
        "quests": ("📜 Quests & Rankings", "Track daily and weekly objectives, claim rewards and compare progress."),
        "alchemy": ("⚗️ Alchemy", "Review recipes, craft potions and use them on growing seeds."),
        "companions": ("🧚 Companions", "Adopt companions and choose which one accompanies your garden."),
        "explore": ("🧭 Explore", "Send expeditions, collect discoveries and unlock new garden biomes."),
        "social": ("🤝 Social Garden", "Visit other gardens, leave gifts, help members and trade resources."),
        "community": ("🛍️ Market & Community", "Shop for supplies and contribute to your server's shared garden."),
        "customize": ("🎨 Customize", "Change your garden's decoration, layout, background and path."),
        "extras": ("✨ More Garden Features", "Manage your seed preferences and explore additional garden features."),
    }

    def __init__(self, cog, author_id, section="home", message=None):
        super().__init__(timeout=300)
        self.cog = cog
        self.author_id = author_id
        self.section = section
        self.message = message
        self._button_count = 0
        self._build()

    def make_embed(self):
        title, description = self.SECTIONS[self.section]
        embed = discord.Embed(title=title, description=description, color=discord.Color.green())
        if self.section == "home":
            embed.add_field(name="Getting started", value="Earn seeds by chatting, plant them, and return when they bloom. Collect flowers, grow your garden and unlock new discoveries.", inline=False)
            embed.set_footer(text="Only the person who opened this menu can use it • Expires in 5 minutes")
        else:
            embed.set_footer(text="Use Back to return to the main garden menu • Buttons expire after 5 minutes")
        return embed

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This FortuneGarden menu belongs to someone else.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    def _add_button(self, label, callback, emoji=None, style=discord.ButtonStyle.secondary):
        row = min(self._button_count // 5, 4)
        button = discord.ui.Button(label=label[:80], emoji=emoji, style=style, row=row)
        async def invoke(interaction):
            await callback(interaction)
        button.callback = invoke
        self.add_item(button)
        self._button_count += 1

    def _add_action(self, label, method, *args, emoji=None, style=discord.ButtonStyle.secondary, **kwargs):
        async def action(interaction):
            await self._call(interaction, method, *args, **kwargs)
        self._add_button(label, action, emoji=emoji, style=style)

    def _add_modal(self, label, title, fields, handler, emoji=None, style=discord.ButtonStyle.secondary):
        async def action(interaction):
            modal = GardenActionModal(self.author_id, title, fields, handler)
            await interaction.response.send_modal(modal)
        self._add_button(label, action, emoji=emoji, style=style)

    def _add_back(self):
        async def back(interaction):
            await self._navigate(interaction, "home")
        self._add_button("Main Menu", back, emoji="🏠", style=discord.ButtonStyle.primary)

    async def _navigate(self, interaction, section):
        new_view = GardenMenuView(self.cog, self.author_id, section, self.message)
        self.stop()
        await interaction.response.edit_message(embed=new_view.make_embed(), view=new_view)

    async def _call(self, interaction, method, *args, _ephemeral=True, **kwargs):
        ctx = GardenInteractionContext(interaction, ephemeral=_ephemeral)
        try:
            if self.cog._resetting:
                if not interaction.response.is_done():
                    await interaction.response.send_message("FortuneGarden is being reset by the bot owner. Please try again shortly.", ephemeral=True)
                else:
                    await interaction.followup.send("FortuneGarden is being reset by the bot owner. Please try again shortly.", ephemeral=True)
                return
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=_ephemeral, thinking=True)
            await getattr(self.cog, method)(ctx, *args, **kwargs)
        except Exception:
            log.exception("FortuneGarden menu action failed: %s", method)
            message = "That garden action could not be completed. Please try again or contact a server administrator if it continues."
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(message, ephemeral=True)
                else:
                    await interaction.response.send_message(message, ephemeral=True)
            except discord.HTTPException:
                pass

    async def _resolve_member(self, interaction, text):
        match = re.search(r"\d{15,22}", text or "")
        if not match:
            await interaction.response.send_message("Please enter a member mention or numeric Discord user ID.", ephemeral=True)
            return None
        member_id = int(match.group())
        member = interaction.guild.get_member(member_id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(member_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None
        if member is None:
            await interaction.response.send_message("I couldn't find that member in this server.", ephemeral=True)
            return None
        return member

    async def _run_member_action(self, interaction, values, method, member_field="member", extra=None):
        member = await self._resolve_member(interaction, values.get(member_field, ""))
        if member is None:
            return
        extra = extra or {}
        await self._call(interaction, method, member, **extra(values))

    def _build(self):
        if self.section == "home":
            sections = [
                ("My Garden", "garden", "🏡"), ("Seeds & Growing", "seeds", "🌱"),
                ("Collections", "collections", "📚"), ("Quests & Rankings", "quests", "📜"),
                ("Alchemy", "alchemy", "⚗️"), ("Companions", "companions", "🧚"),
                ("Explore", "explore", "🧭"), ("Social", "social", "🤝"),
                ("Market & Community", "community", "🛍️"), ("Customize", "customize", "🎨"),
                ("More", "extras", "✨"),
            ]
            for label, section, emoji in sections:
                async def navigate(interaction, target=section):
                    await self._navigate(interaction, target)
                self._add_button(label, navigate, emoji=emoji, style=discord.ButtonStyle.primary)
            async def close(interaction):
                self.stop()
                for item in self.children:
                    item.disabled = True
                await interaction.response.edit_message(content="FortuneGarden menu closed.", embed=None, view=self)
            self._add_button("Close", close, emoji="✖️", style=discord.ButtonStyle.danger)
            return

        if self.section == "garden":
            self._add_action("Garden Overview", "show_garden_profile", emoji="🏡", style=discord.ButtonStyle.success)
            self._add_action("Visual Garden", "gardenrender", None, emoji="🖼️")
            self._add_action("Weather & Moon", "gardenweather", emoji="🌦️")
            self._add_action("World Tree", "worldtree", "view", emoji="🌳")
            async def nourish(interaction, values):
                await self._call(interaction, "worldtree", "nourish", flower=values["flower"])
            self._add_modal("Nourish Tree", "Nourish your World Tree", [("flower", "Flower name", "Enter a flower you own", True)], nourish, emoji="🌸")
            async def prestige(interaction, values):
                if values["confirm"].strip().upper() != "PRESTIGE":
                    return await interaction.response.send_message("Prestige cancelled. Type PRESTIGE exactly to confirm.", ephemeral=True)
                await self._call(interaction, "gardenprestige", "confirm")
            self._add_modal("Prestige", "Confirm Garden Prestige", [("confirm", "Type PRESTIGE to confirm", "PRESTIGE", True)], prestige, emoji="⭐", style=discord.ButtonStyle.danger)
            self._add_action("Claim Birthday Gift", "gardenbirthday", "claim", None, emoji="🎂", style=discord.ButtonStyle.success)
            async def birthday(interaction, values):
                await self._call(interaction, "gardenbirthday", "set", values["date"])
            self._add_modal("Set Birthday", "Set your optional birthday", [("date", "Birthday (MM-DD)", "Example: 04-21", True)], birthday, emoji="📅")

        elif self.section == "seeds":
            self._add_action("Seed Inventory", "fortuneseeds", None, emoji="🎒", style=discord.ButtonStyle.success)
            self._add_action("Growing Seeds", "listfortunes", emoji="⌛")
            for key, info in SEED_TYPES.items():
                self._add_action(f"Plant {info['label']}", "plantfortune", key, emoji=info["emoji"], style=discord.ButtonStyle.success)
            async def seed_id_action(interaction, values, method):
                await self._call(interaction, method, values["seed_id"])
            for label, method, emoji in (("Water Seed", "waterfortune", "💧"), ("Use Fertilizer", "fertilizefortune", "🌿"), ("Remove Seed", "removefortune", "🗑️")):
                async def handler(interaction, values, target=method):
                    await seed_id_action(interaction, values, target)
                self._add_modal(label, f"{label}", [("seed_id", "Seed ID", "Paste the ID shown in your growing seed list", True)], handler, emoji=emoji)

        elif self.section == "collections":
            self._add_action("Flower Collection", "gardenflowers", None, emoji="🌸", style=discord.ButtonStyle.success)
            self._add_action("Botanical Journal", "gardenjournal", None, emoji="📖")
            self._add_action("Achievements", "gardenachievements", None, emoji="🏆")
            self._add_action("Reward History", "fortunehistory", None, emoji="📜")
            self._add_action("Seasonal Event", "fortuneevent", emoji="🎪")

        elif self.section == "quests":
            self._add_action("Daily & Weekly Quests", "gardenquests", emoji="📜", style=discord.ButtonStyle.success)
            async def claim(interaction, values):
                await self._call(interaction, "gardenquestclaim", values["quest_id"])
            self._add_modal("Claim Quest", "Claim a completed quest", [("quest_id", "Quest ID", "For example: d_plant or w_bloom", True)], claim, emoji="🎁")
            self._add_action("Seasonal Event", "fortuneevent", emoji="🎪")
            self._add_action("Level Leaderboard", "gardenleaderboard", "level", emoji="🏅")
            self._add_action("Flower Leaderboard", "gardenleaderboard", "flowers", emoji="🌸")
            self._add_action("Seasonal Leaderboard", "gardenleaderboard", "seasonal", emoji="🍂")
            self._add_action("Festival Leaderboard", "gardenleaderboard", "festival", emoji="🎪")

        elif self.section == "alchemy":
            self._add_action("View Recipes", "gardenbrew", "recipes", None, None, emoji="📖", style=discord.ButtonStyle.success)
            for key, recipe in RECIPES.items():
                self._add_action(f"Craft {recipe['label']}", "gardenbrew", "craft", key, None, emoji="⚗️")
            async def use_potion(interaction, values):
                await self._call(interaction, "gardenbrew", "use", values["potion"], values["seed_id"])
            potion_keys = ", ".join(RECIPES)
            self._add_modal("Use Potion", "Use a potion on a growing seed", [("potion", "Potion ID", potion_keys[:100], True), ("seed_id", "Seed ID", "Paste the growing seed ID", True)], use_potion, emoji="🧪")

        elif self.section == "companions":
            self._add_action("My Companions", "gardencompanion", "list", emoji="🐾", style=discord.ButtonStyle.success)
            for key, info in COMPANIONS.items():
                async def adopt(interaction, target=key):
                    await self._call(interaction, "gardenadopt", target)
                self._add_button(f"Adopt {info['label']}", adopt, emoji=info["emoji"])
            async def equip(interaction, values):
                await self._call(interaction, "gardencompanion", "equip", companion=values["companion"])
            self._add_modal("Equip Companion", "Equip a discovered companion", [("companion", "Companion", "Enter its name or key (e.g. fairy)", True)], equip, emoji="✨")

        elif self.section == "explore":
            self._add_action("Expedition Guide", "gardenexpedition", "list", None, emoji="🧭", style=discord.ButtonStyle.success)
            for key, info in EXPEDITIONS.items():
                async def start(interaction, target=key):
                    await self._call(interaction, "gardenexpedition", "start", target)
                self._add_button(f"Start {info['label']}", start, emoji="🗺️")
            self._add_action("Collect Expedition", "gardenexpedition", "collect", None, emoji="🎁")
            self._add_action("View Biomes", "gardenbiome", "list", None, emoji="🌍")
            for key, info in BIOMES.items():
                async def biome(interaction, target=key):
                    await self._call(interaction, "gardenbiome", "set", target)
                self._add_button(info["label"], biome, emoji="🌱")
            self._add_action("Weather & Moon", "gardenweather", emoji="🌦️")

        elif self.section == "social":
            self._add_action("My Guestbook", "gardenguestbook", None, emoji="📖", style=discord.ButtonStyle.success)
            async def visit(interaction, values):
                member = await self._resolve_member(interaction, values["member"])
                if member:
                    await self._call(interaction, "gardenvisit", member, compliment=values["compliment"] or "Your garden is lovely!", _ephemeral=False)
            self._add_modal("Visit a Garden", "Visit another member's garden", [("member", "Member mention or ID", "@member or numeric user ID", True), ("compliment", "Leave a compliment", "Your garden is lovely!", False)], visit, emoji="🏡")
            async def guestbook(interaction, values):
                member = await self._resolve_member(interaction, values["member"])
                if member:
                    await self._call(interaction, "gardenguestbook", member)
            self._add_modal("View Guestbook", "Read another garden's guestbook", [("member", "Member mention or ID", "@member or numeric user ID", True)], guestbook, emoji="📚")
            async def gift(interaction, values):
                member = await self._resolve_member(interaction, values["member"])
                if member:
                    await self._call(interaction, "gardengift", member, flower=values["flower"], _ephemeral=False)
            self._add_modal("Gift a Flower", "Send a flower to another member", [("member", "Member mention or ID", "@member or numeric user ID", True), ("flower", "Flower name", "Enter the flower you want to gift", True)], gift, emoji="🎁")
            async def help_water(interaction, values):
                member = await self._resolve_member(interaction, values["member"])
                if member:
                    await self._call(interaction, "gardenhelpwater", member, values["seed_id"])
            self._add_modal("Help Water", "Water another member's seed", [("member", "Member mention or ID", "@member or numeric user ID", True), ("seed_id", "Seed ID", "Their growing seed ID", True)], help_water, emoji="💧")
            async def offer(interaction, values):
                member = await self._resolve_member(interaction, values["member"])
                if member:
                    try:
                        give_type, give_item = values["give"].split(":", 1)
                        want_type, want_item = values["want"].split(":", 1)
                        amount = int(values.get("amount") or "1")
                    except (ValueError, TypeError):
                        return await interaction.response.send_message("Use `type:item` for both sides, for example `flower:Dandelion` and `seed:golden`, and enter a whole-number amount.", ephemeral=True)
                    await self._call(interaction, "gardenoffer", member, give_type.strip(), give_item.strip(), want_type.strip(), want_item.strip(), amount, _ephemeral=False)
            self._add_modal("Offer a Trade", "Create a player-to-player trade", [("member", "Recipient mention or ID", "@member or numeric user ID", True), ("give", "What you offer (type:item)", "e.g. flower:Dandelion", True), ("want", "What you want (type:item)", "e.g. seed:golden", True), ("amount", "Amount per side", "1", False)], offer, emoji="🤝")
            async def trade(interaction, values):
                await self._call(interaction, "gardentrade", values["offer_id"], values["decision"].lower())
            self._add_modal("Respond to Trade", "Accept or decline a trade offer", [("offer_id", "Trade offer ID", "Paste the offer ID", True), ("decision", "Decision", "accept or decline", True)], trade, emoji="✅")

        elif self.section == "community":
            self._add_action("Today's Market", "gardenmarket", emoji="🛍️", style=discord.ButtonStyle.success)
            async def buy(interaction, values):
                try:
                    amount = int(values.get("amount") or "1")
                except ValueError:
                    return await interaction.response.send_message("Amount must be a whole number.", ephemeral=True)
                await self._call(interaction, "gardenbuy", values["item"], amount)
            self._add_modal("Buy Supplies", "Purchase from today's market", [("item", "Market item key", "fertilizer, growth_potion, fortune_elixir, common_seed, golden_seed", True), ("amount", "Quantity (1–25)", "1", True)], buy, emoji="🪙")
            self._add_action("Community Garden", "gardencommunity", emoji="🌳")
            async def contribute(interaction, values):
                try:
                    amount = int(values.get("amount") or "1")
                except ValueError:
                    return await interaction.response.send_message("Amount must be a whole number.", ephemeral=True)
                await self._call(interaction, "gardencontribute", values["kind"], values["item"], amount)
            self._add_modal("Contribute", "Contribute to the community garden", [("kind", "Contribution type", "flower, seed or credits", True), ("item", "Item name/type or credit amount", "e.g. Dandelion, common, or 100", True), ("amount", "Quantity (credits use item field)", "1", False)], contribute, emoji="🌱")
            self._add_action("Claim Community Rewards", "gardencommunityclaim", emoji="🎁")
            self._add_action("World Tree", "worldtree", "view", emoji="🌳")

        elif self.section == "customize":
            self._add_action("View Decorations", "gardendecorate", decoration="list", emoji="🪴", style=discord.ButtonStyle.success)
            async def decorate(interaction, values):
                await self._call(interaction, "gardendecorate", decoration=values["decoration"])
            self._add_modal("Equip Decoration", "Equip an unlocked decoration", [("decoration", "Decoration name or 'none'", "Enter a decoration you unlocked", True)], decorate, emoji="🏡")
            async def design(interaction, values):
                await self._call(interaction, "gardendesign", values["category"].lower(), choice=values["choice"].lower())
            self._add_modal("Change Garden Design", "Set your garden layout, background or path", [("category", "Design category", "layout, background or path", True), ("choice", "Choice", "e.g. cottage, emerald or stone", True)], design, emoji="🎨")
            self._add_action("View Garden Biomes", "gardenbiome", "list", None, emoji="🌍")

        elif self.section == "extras":
            self._add_action("Seed Preferences: Status", "seedopt", "status", emoji="🌱", style=discord.ButtonStyle.success)
            self._add_action("Opt In to Seed Drops", "seedopt", "on", emoji="✅")
            self._add_action("Opt Out of Seed Drops", "seedopt", "off", emoji="🚫")
            self._add_action("Seasonal Event", "fortuneevent", emoji="🎪")
            self._add_action("Garden Leaderboard", "gardenleaderboard", "level", emoji="🏆")

        self._add_back()


class FortuneGarden(commands.Cog):
    @commands.command(name="fortunegarden", help="Show the FortuneGarden command list.")
    async def fortunegarden(self, ctx):
        await self.bot.send_help_for(ctx, self)

    @commands.guild_only()
    @commands.command(name="forgarden", aliases=["mygarden"], help="Open the interactive FortuneGarden menu.")
    async def forgarden(self, ctx):
        view = GardenMenuView(self, ctx.author.id)
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            garden = await self._get_garden(self.config.user(ctx.author))
        embed = view.make_embed()
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        embed.add_field(
            name="🌱 Seed Inventory",
            value=" • ".join(f"{SEED_TYPES[key]['emoji']} {garden['seed_inventory'].get(key, 0)}" for key in SEED_TYPES),
            inline=False,
        )
        embed.add_field(name="⭐ Garden Level", value=f"Level **{garden.get('garden_level', 1)}** · {int(garden.get('garden_xp', 0)) % 100}/100 XP", inline=True)
        embed.add_field(name="🌸 Flowers", value=f"{sum(int(value) for value in garden.get('flowers', {}).values())} collected", inline=True)
        embed.add_field(name="🌳 World Tree", value=f"Level {garden.get('world_tree_level', 1)}", inline=True)
        embed.add_field(name="🧚 Companion", value=COMPANIONS.get(garden.get('equipped_companion'), {}).get("label", "None equipped"), inline=True)
        embed.add_field(name="🌍 Biome", value=BIOMES.get(garden.get('equipped_biome', 'meadow'), BIOMES['meadow'])['label'], inline=True)
        embed.add_field(name="🏆 Prestige", value=str(garden.get('prestige', 0)), inline=True)
        view.message = await ctx.send(embed=embed, view=view)

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
            trade_offers={},
            community_garden={"xp": 0, "level": 1, "contributions": {}, "milestones": []},
        )
        user_defaults = {
            "seeds": 0,
            "last_earned": None,
            "opt_out": False,
            "garden": None,
        }
        self.config.register_user(**user_defaults)
        self.config.register_member(**user_defaults)
        self.config.register_global(member_migration_version=0)
        self._guild_locks = {}
        self._migration_lock = asyncio.Lock()
        self._migration_complete = False
        self._member_locks = {}
        self._reset_lock = asyncio.Lock()
        self._resetting = False

    async def cog_check(self, ctx):
        if self._resetting and ctx.command and ctx.command.name != "fortunereset":
            await ctx.send("FortuneGarden is being reset by the bot owner. Please try again shortly.")
            return False
        return True

    async def _migrate_member_data(self):
        if self._migration_complete:
            return
        async with self._migration_lock:
            if self._migration_complete:
                return
            if int(await self.config.member_migration_version()) >= 1:
                self._migration_complete = True
                return
            legacy = await self.config.all_members()
            merged_rows = {}
            for guild_members in legacy.values():
                for user_id, data in guild_members.items():
                    merged_rows.setdefault(str(user_id), []).append(data)
            for user_id, rows in merged_rows.items():
                user_conf = self.config.user_from_id(int(user_id))
                current = await user_conf.all()
                if isinstance(current.get("garden"), dict):
                    continue
                if int(current.get("seeds", 0)) > 0 or current.get("last_earned") or current.get("opt_out"):
                    continue
                combined = create_garden()
                last_earned = []
                opt_out = False
                has_legacy_data = False
                history = []
                for row in rows:
                    if row.get("last_earned"):
                        last_earned.append(row["last_earned"])
                    opt_out = opt_out or bool(row.get("opt_out"))
                    source = row.get("garden")
                    if not isinstance(source, dict):
                        legacy_seeds = max(0, int(row.get("seeds", 0)))
                        source = create_garden(legacy_seeds)
                    inventory = source.get("seed_inventory") if isinstance(source.get("seed_inventory"), dict) else {"common": source.get("seeds", row.get("seeds", 0))}
                    for seed_type in SEED_TYPES:
                        combined["seed_inventory"][seed_type] += max(0, int(inventory.get(seed_type, 0)))
                    for flower, count in source.get("flowers", {}).items():
                        combined["flowers"][flower] = int(combined["flowers"].get(flower, 0)) + max(0, int(count))
                    for item, count in (source.get("items") or {}).items():
                        combined["items"][item] = int(combined["items"].get(item, 0)) + max(0, int(count))
                    for item, count in (source.get("potions") or {}).items():
                        combined["potions"][item] = int(combined["potions"].get(item, 0)) + max(0, int(count))
                    for field in ("garden_xp", "world_tree_xp", "prestige", "water_streak", "visit_count"):
                        combined[field] = max(int(combined.get(field, 0)), int(source.get(field, 0)))
                    for field in ("total_planted", "total_blooms"):
                        combined[field] += max(0, int(source.get(field, 0)))
                    for field in ("achievements", "applied_reward_ids", "event_claims", "unlocked_decorations", "companions", "biomes"):
                        for value in source.get(field, []) or []:
                            if value not in combined[field]:
                                combined[field].append(value)
                    for guild_key, claimed_levels in (source.get("community_claims") or {}).items() if isinstance(source.get("community_claims"), dict) else []:
                        combined["community_claims"].setdefault(str(guild_key), [])
                        combined["community_claims"][str(guild_key)] = sorted(set(combined["community_claims"][str(guild_key)] + list(claimed_levels)))
                    for event_key, value in (source.get("event_progress") or {}).items():
                        combined["event_progress"][event_key] = int(combined["event_progress"].get(event_key, 0)) + int(value)
                    history.extend(source.get("reward_history", []) or [])
                    combined["guestbook"].extend(source.get("guestbook", []) or [])
                    for field in ("last_water_date", "daily_water_date", "birthday", "birthday_claimed_year", "equipped_companion", "equipped_biome", "equipped_decoration", "expedition"):
                        if source.get(field) and not combined.get(field):
                            combined[field] = source[field]
                    if source.get("design") and combined.get("design") == create_garden().get("design"):
                        combined["design"] = source["design"]
                    has_legacy_data = has_legacy_data or source != create_garden() or bool(row.get("seeds"))
                combined["garden_level"] = 1 + int(combined["garden_xp"]) // 100
                combined["world_tree_level"] = 1 + int(combined["world_tree_xp"]) // 100
                combined["seeds"] = sum(combined["seed_inventory"].values())
                combined["reward_history"] = sorted(history, key=lambda item: item.get("timestamp", ""))[-20:]
                combined["guestbook"] = combined["guestbook"][-20:]
                if not has_legacy_data and not last_earned and not opt_out:
                    continue
                await self._save_garden(user_conf, combined)
                if last_earned:
                    try:
                        await user_conf.last_earned.set(max(last_earned, key=lambda value: datetime.fromisoformat(value)))
                    except (TypeError, ValueError):
                        await user_conf.last_earned.set(last_earned[-1])
                await user_conf.opt_out.set(opt_out)
            await self.config.member_migration_version.set(1)
            self._migration_complete = True
            log.info("FortuneGarden migrated legacy per-server member data to global user profiles.")

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
        key = int(user_id)
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
        if not self._migration_complete and int(await self.config.member_migration_version()) < 1:
            await self._migrate_member_data()
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

    def _refresh_quests(self, garden, now=None):
        now = now or datetime.utcnow()
        daily_key, weekly_key = quest_periods(now)
        state = garden.setdefault("quest_state", {})
        if state.get("daily_key") != daily_key:
            rng = random.Random(daily_key + str(garden.get("quest_salt", 0)))
            selected = rng.sample(DAILY_QUEST_POOL, 3)
            state["daily_key"] = daily_key
            state["daily"] = [{**task, "event": task["id"], "id": f"d_{task['id']}", "progress": 0, "claimed": False} for task in selected]
        if state.get("weekly_key") != weekly_key:
            rng = random.Random(weekly_key + str(garden.get("quest_salt", 0)))
            selected = rng.sample(WEEKLY_QUEST_POOL, 3)
            state["weekly_key"] = weekly_key
            state["weekly"] = [{**task, "event": task["id"], "id": f"w_{task['id']}", "progress": 0, "claimed": False} for task in selected]

    def _progress_quests(self, garden, event, amount=1):
        self._refresh_quests(garden)
        state = garden.setdefault("quest_state", {})
        for period in ("daily", "weekly"):
            for task in state.get(period, []):
                if task.get("event", task.get("id")) == event and not task.get("claimed"):
                    task["progress"] = min(int(task.get("target", 1)), int(task.get("progress", 0)) + int(amount))

    def _add_world_tree_xp(self, garden, amount):
        garden["world_tree_xp"] = max(0, int(garden.get("world_tree_xp", 0)) + int(amount))
        garden["world_tree_level"] = 1 + garden["world_tree_xp"] // 100

    def _asset_count(self, garden, asset_type, item):
        if asset_type == "seed":
            return int(garden.get("seed_inventory", {}).get(item, 0)) if item in SEED_TYPES else 0
        if asset_type == "flower":
            found = next((name for name in garden.get("flowers", {}) if name.lower() == item.lower()), None)
            return int(garden.get("flowers", {}).get(found, 0)) if found else 0
        if asset_type == "item":
            if item == "fertilizer":
                return int(garden.get("items", {}).get("fertilizer", 0))
            return int(garden.get("potions", {}).get(item, 0))
        return 0

    def _transfer_asset(self, garden, asset_type, item, amount, add=False):
        amount = int(amount)
        if asset_type == "seed":
            if item not in SEED_TYPES:
                raise ValueError("Unknown seed type.")
            key = item
            store = garden.setdefault("seed_inventory", {})
            if not add and int(store.get(key, 0)) < amount:
                raise ValueError("Not enough of that seed.")
            store[key] = max(0, int(store.get(key, 0)) + (amount if add else -amount))
        elif asset_type == "flower":
            key = next((name for name in garden.get("flowers", {}) if name.lower() == item.lower()), None)
            if key is None:
                key = next((name for name in FLOWERS if name.lower() == item.lower()), None)
            if key is None and add:
                key = item
            if key is None or (not add and int(garden.get("flowers", {}).get(key, 0)) < amount):
                raise ValueError("Not enough of that flower.")
            flowers = garden.setdefault("flowers", {})
            flowers[key] = max(0, int(flowers.get(key, 0)) + (amount if add else -amount))
        elif asset_type == "item":
            store = garden.setdefault("items", {}) if item == "fertilizer" else garden.setdefault("potions", {})
            if item not in ("fertilizer", *RECIPES.keys()):
                raise ValueError("Unknown garden item.")
            if not add and int(store.get(item, 0)) < amount:
                raise ValueError("Not enough of that item.")
            store[item] = max(0, int(store.get(item, 0)) + (amount if add else -amount))
        else:
            raise ValueError("Asset type must be seed, flower or item.")

    def _seed_count(self, garden):
        return sum(max(0, int(value)) for value in garden.get("seed_inventory", {}).values())

    def _add_xp(self, garden, amount):
        multiplier = 1.0 + max(0, int(garden.get("permanent_xp_bonus", 0))) / 100.0
        if garden.get("equipped_companion") == "owl":
            multiplier += 0.10
        garden["garden_xp"] = max(0, int(garden.get("garden_xp", 0)) + int(int(amount) * multiplier))
        new_level = 1 + garden["garden_xp"] // 100
        old_level = int(garden.get("garden_level", 1))
        garden["garden_level"] = new_level
        unlocked = garden.setdefault("unlocked_decorations", [])
        for level, decoration in DECORATION_UNLOCKS.items():
            if new_level >= level and decoration not in unlocked:
                unlocked.append(decoration)
        return new_level - old_level

    def _check_achievements(self, garden):
        newly_earned = []
        while True:
            flowers = garden.get("flowers", {})
            discovered = [name for name, count in flowers.items() if int(count) > 0]
            unique_flowers = len(discovered)
            total_flowers = sum(max(0, int(count)) for count in flowers.values())
            rarities = {FLOWERS.get(name, "Common") for name in discovered}
            achievements = garden.setdefault("achievements", [])
            earned = set(achievements)
            checks = {
                "First Plant": int(garden.get("total_planted", 0)) >= 1,
                "First Bloom": int(garden.get("total_blooms", 0)) >= 1,
                "Dedicated Gardener": int(garden.get("total_blooms", 0)) >= 10,
                "Master Gardener": int(garden.get("total_blooms", 0)) >= 50,
                "Evergreen Heart": int(garden.get("total_blooms", 0)) >= 100,
                "Seed Sower": int(garden.get("total_planted", 0)) >= 10,
                "Seed Artisan": int(garden.get("total_planted", 0)) >= 50,
                "Seed Legend": int(garden.get("total_planted", 0)) >= 100,
                "Green Thumb": int(garden.get("garden_level", 1)) >= 5,
                "Verdant Master": int(garden.get("garden_level", 1)) >= 10,
                "Garden Legend": int(garden.get("garden_level", 1)) >= 25,
                "Botanist": unique_flowers >= 5,
                "Collector's Pride": unique_flowers >= 10,
                "Living Herbarium": unique_flowers >= 20,
                "Bouquet Maker": total_flowers >= 50,
                "Rare Discovery": "Rare" in rarities,
                "Beyond the Ordinary": "Epic" in rarities,
                "Once in a Lifetime": "Legendary" in rarities,
                "Faithful Waterer": int(garden.get("water_streak", 0)) >= 7,
                "Rainkeeper": int(garden.get("water_streak", 0)) >= 14,
                "Water Bearer": int(garden.get("total_waterings", 0)) >= 100,
                "Alchemist's Apprentice": int(garden.get("total_crafted", 0)) >= 1,
                "Master Alchemist": int(garden.get("total_crafted", 0)) >= 10,
                "Grand Alchemist": int(garden.get("total_crafted", 0)) >= 50,
                "First Expedition": int(garden.get("total_expeditions", 0)) >= 1,
                "Pathfinder": int(garden.get("total_expeditions", 0)) >= 10,
                "World Wanderer": int(garden.get("total_expeditions", 0)) >= 25,
                "Master Explorer": int(garden.get("total_expeditions", 0)) >= 50,
                "Friendly Face": int(garden.get("total_visits_made", 0)) >= 5,
                "Garden Ambassador": int(garden.get("total_visits_made", 0)) >= 25,
                "Beloved Garden": int(garden.get("visit_count", 0)) >= 10,
                "Grand Host": int(garden.get("visit_count", 0)) >= 50,
                "Generous Gardener": int(garden.get("total_gifts_sent", 0)) >= 10,
                "Fair Trader": int(garden.get("total_trades_completed", 0)) >= 5,
                "Festival Friend": int(garden.get("event_blooms_total", 0)) >= 5,
                "Festival Legend": int(garden.get("event_blooms_total", 0)) >= 30,
                "Companion Keeper": len(garden.get("companions", [])) >= 3,
                "Menagerie": len(garden.get("companions", [])) >= len(COMPANIONS),
                "Biome Explorer": len(garden.get("biomes", [])) >= 3,
                "World Traveller": len(garden.get("biomes", [])) >= len(BIOMES),
                "Decorative Touch": len(garden.get("unlocked_decorations", [])) >= 5,
                "Quest Collector": int(garden.get("total_quests_claimed", 0)) >= 10,
                "Community Roots": int(garden.get("total_community_points", 0)) >= 250,
                "Heart of the Village": int(garden.get("total_community_points", 0)) >= 1000,
                "World Tree Keeper": int(garden.get("world_tree_level", 1)) >= 10,
                "Prestigious": int(garden.get("prestige", 0)) >= 1,
                "Fivefold Prestige": int(garden.get("prestige", 0)) >= 5,
                "Weather Watcher": len(garden.get("weather_seen", [])) >= 6,
                "Market Regular": int(garden.get("total_items_purchased", 0)) >= 10,
                "Seasonal Collector": len([name for name in discovered if FLOWERS.get(name) == "Seasonal"]) >= 4,
                "Moon Phase Scholar": len(garden.get("moon_phases_seen", [])) >= 8,
                "Garden Archivist": len(garden.get("reward_history", [])) >= 20,
            }
            fresh = [name for name, condition in checks.items() if condition and name not in earned]
            if not fresh:
                break
            for name in fresh:
                achievements.append(name)
                newly_earned.append(name)
                reward = ACHIEVEMENT_REWARDS.get(name, {})
                self._add_xp(garden, int(reward.get("xp", 0)))
                for seed_type, count in reward.get("seeds", {}).items():
                    if seed_type in SEED_TYPES:
                        garden.setdefault("seed_inventory", {})[seed_type] = int(garden["seed_inventory"].get(seed_type, 0)) + int(count)
                for item, count in reward.get("items", {}).items():
                    garden.setdefault("items", {})[item] = int(garden.get("items", {}).get(item, 0)) + int(count)
                for potion, count in reward.get("potions", {}).items():
                    garden.setdefault("potions", {})[potion] = int(garden.get("potions", {}).get(potion, 0)) + int(count)
        garden["seeds"] = self._seed_count(garden)
        return newly_earned

    def _add_flower(self, garden, flower_name):
        flowers = garden.setdefault("flowers", {})
        flowers[flower_name] = max(0, int(flowers.get(flower_name, 0))) + 1

    def _choose_seed_type(self):
        names = list(SEED_TYPES)
        weights = [SEED_TYPES[name]["weight"] for name in names]
        return random.choices(names, weights=weights, k=1)[0]

    def _choose_flower(self, seed_type, event, companion=None, biome="meadow", weather=None):
        rarity_weights = {
            "common": [60, 25, 11, 3, 1],
            "golden": [45, 27, 18, 7, 3],
            "moonlight": [40, 25, 20, 10, 5],
            "ancient": [30, 25, 25, 14, 6],
        }
        rarities = ["Common", "Uncommon", "Rare", "Epic", "Legendary"]
        weights = list(rarity_weights.get(seed_type, rarity_weights["common"]))
        if companion == "fairy":
            weights[2] *= 1.25
            weights[3] *= 1.5
            weights[4] *= 2
        elif companion == "spirit":
            weights[3] *= 1.15
            weights[4] *= 1.5
        elif companion == "bee":
            weights[1] *= 1.25
            weights[2] *= 1.10
        elif companion == "phoenix":
            weights[3] *= 1.10
            weights[4] *= 1.10
        weather_info = WEATHER_EFFECTS.get(weather or "", {})
        flower_bonus = float(weather_info.get("flower_bonus", 1.0))
        if flower_bonus > 1:
            weights[2] *= flower_bonus
            weights[3] *= flower_bonus
            weights[4] *= flower_bonus
        special_flower = weather_info.get("special_flower")
        if special_flower and random.random() < float(weather_info.get("special_chance", 0)):
            return special_flower, FLOWERS.get(special_flower, "Seasonal")
        rarity = random.choices(rarities, weights=weights, k=1)[0]
        biome_pool = set(BIOME_FLOWERS.get(biome, BIOME_FLOWERS["meadow"]))
        candidates = [name for name, flower_rarity in FLOWERS.items() if flower_rarity == rarity and name in biome_pool]
        if not candidates:
            candidates = [name for name, flower_rarity in FLOWERS.items() if flower_rarity == rarity]
        if event and random.random() < 0.18:
            return event["flower"], "Seasonal"
        if not candidates:
            candidates = ["Dandelion"]
        return random.choice(candidates), rarity

    def _make_reward(self, reward_type, seed_type, guild_data, event, companion=None, biome="meadow", weather=None):
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
            flower, rarity = self._choose_flower(seed_type, event, companion, biome, weather)
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
                flower, rarity = self._choose_flower(seed_type, event, companion, biome, weather)
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

    async def _apply_member_bloom(self, member, fid, reward, reward_text, event, seed_limit, festival=None, weather=None, weather_bonus=0):
        lock = self._member_lock(member.guild.id, member.id)
        async with lock:
            member_conf = self.config.user(member)
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
            garden["event_blooms_total"] = int(garden.get("event_blooms_total", 0)) + 1
            garden["festival_blooms_total"] = int(garden.get("festival_blooms_total", 0)) + 1
            self._progress_quests(garden, "festival", 1)
            self._progress_quests(garden, "bloom", 1)
            if kind == "flower" or (kind == "mystery" and reward.get("prize", {}).get("kind") == "flower"):
                self._progress_quests(garden, "flower", 1)
            xp_gain = 25 + max(0, int(weather_bonus))
            if info_bonus := int(reward.get("xp_bonus", 0)):
                xp_gain += max(0, info_bonus)
            self._add_xp(garden, xp_gain)
            self._add_world_tree_xp(garden, 5)
            event_notes = []
            if reward.get("extra_flower"):
                extra_flower = reward["extra_flower"]
                self._add_flower(garden, extra_flower)
                event_notes.append(f"🌼 Weather blessing: an extra {extra_flower} bloomed")
            if reward.get("bonus_fertilizer"):
                garden.setdefault("items", {})["fertilizer"] = int(garden.get("items", {}).get("fertilizer", 0)) + int(reward["bonus_fertilizer"])
                event_notes.append(f"🌿 Weather blessing: {reward['bonus_fertilizer']} Fertilizer found")
            event_progress = garden.setdefault("event_progress", {})
            event_key = event["key"]
            event_progress[event_key] = int(event_progress.get(event_key, 0)) + 1
            event_claims = garden.setdefault("event_claims", [])
            points = event_progress[event_key]
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
            if festival:
                festival_key = festival["key"]
                festival_progress = garden.setdefault("festival_progress", {})
                festival_progress[festival_key] = int(festival_progress.get(festival_key, 0)) + 1
                festival_claims = garden.setdefault("festival_claims", [])
                festival_points = festival_progress[festival_key]
                if festival_key not in garden.setdefault("festival_history", []):
                    garden["festival_history"].append(festival_key)
                if festival_points >= 3 and f"{festival_key}:3" not in festival_claims:
                    self._add_flower(garden, festival["flower"])
                    festival_claims.append(f"{festival_key}:3")
                    event_notes.append(f"{festival['emoji']} Festival reward: {festival['flower']} discovered")
                if festival_points >= 7 and f"{festival_key}:7" not in festival_claims:
                    garden.setdefault("potions", {})["fortune_elixir"] = int(garden["potions"].get("fortune_elixir", 0)) + 1
                    festival_claims.append(f"{festival_key}:7")
                    event_notes.append("⚗️ Festival reward: Fortune Elixir earned")
                if festival_points >= 14 and f"{festival_key}:14" not in festival_claims:
                    decoration = f"{festival['name']} Keepsake"
                    if decoration not in garden.setdefault("unlocked_decorations", []):
                        garden["unlocked_decorations"].append(decoration)
                        event_notes.append(f"🎀 Festival reward: {decoration} unlocked")
                    else:
                        self._add_xp(garden, 50)
                        event_notes.append("⭐ Festival repeat reward: 50 garden XP")
                    festival_claims.append(f"{festival_key}:14")

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
                festival = current_festival_event(now)

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
                    member_garden = await self._get_garden(self.config.user(member))
                    companion = member_garden.get("equipped_companion")
                    biome = member_garden.get("equipped_biome", "meadow")
                    if not isinstance(info.get("reward"), dict):
                        weather = info.get("weather")
                        reward_type = self._roll_reward_type(guild_data, seed_type, bool(info.get("fertilized")))
                        if companion == "dragon":
                            reward_type = random.choices([reward_type, "flower", "jackpot"], weights=[75, 20, 5], k=1)[0]
                        if info.get("prism_boost"):
                            reward_type = random.choices([reward_type, "flower", "jackpot"], weights=[35, 50, 15], k=1)[0]
                        elif info.get("fortune_boost"):
                            reward_type = random.choices([reward_type, "flower", "jackpot"], weights=[55, 35, 10], k=1)[0]
                        if info.get("pollinator_boost"):
                            reward_type = "flower"
                        if info.get("dream_boost"):
                            reward_type = "prompt"
                        reward = self._make_reward(reward_type, seed_type, guild_data, event, companion, biome, weather)
                        festival_flower_reward = reward if reward.get("kind") == "flower" else reward.get("prize", {}) if reward.get("kind") == "mystery" else {}
                        if festival and festival_flower_reward.get("kind") == "flower" and random.random() < 0.18:
                            festival_flower_reward["flower"] = festival["flower"]
                            festival_flower_reward["rarity"] = FLOWERS.get(festival["flower"], "Seasonal")
                        if info.get("moonlight_boost") and reward.get("kind") == "flower":
                            flower, rarity = self._choose_flower("moonlight", event, companion, biome, weather)
                            reward["flower"], reward["rarity"] = flower, rarity
                        if info.get("fertilized") or info.get("aurora_boost"):
                            flower_reward = reward if reward.get("kind") == "flower" else reward.get("prize", {}) if reward.get("kind") == "mystery" else {}
                            if flower_reward.get("kind") == "flower":
                                flower, rarity = self._choose_flower("golden", event, companion, biome, weather)
                                flower_reward["flower"] = flower
                                flower_reward["rarity"] = rarity
                        if info.get("sunfire_boost") and reward.get("kind") in ("currency", "jackpot"):
                            reward["amount"] = int(reward.get("amount", 0) * 1.35)
                        if info.get("stargazer_boost"):
                            reward["xp_bonus"] = 30
                            if reward.get("kind") != "flower" and random.random() < 0.20:
                                reward["extra_flower"] = self._choose_flower("moonlight", event, companion, biome, weather)[0]
                        if info.get("nectar_boost"):
                            reward["xp_bonus"] = int(reward.get("xp_bonus", 0)) + 40
                        if info.get("rootbound_boost"):
                            reward["xp_bonus"] = int(reward.get("xp_bonus", 0)) + 60
                        if info.get("pollinator_boost") and reward.get("kind") == "flower" and random.random() < 0.20:
                            reward["extra_flower"] = self._choose_flower(seed_type, event, companion, biome, weather)[0]
                        weather_info = WEATHER_EFFECTS.get(weather or "", {})
                        if weather_info.get("bonus_fertilizer_chance") and random.random() < float(weather_info["bonus_fertilizer_chance"]):
                            reward["bonus_fertilizer"] = 1
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
                            weather = info.get("weather")
                            weather_bonus = int(WEATHER_EFFECTS.get(weather or "", {}).get("xp_bonus", 0))
                            notes = await self._apply_member_bloom(member, fid, reward, reward_text, event, seed_limit, festival, weather, weather_bonus)
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
                    embed.set_image(url=REWARD_BANNERS.get(reward.get("kind")) or PLANT_BANNER)
                    embed.set_footer(text=f"Seed ID: {fid} • {event['name']} • {festival['name']}")

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
        if self._resetting:
            return
        try:
            await self._process_due_seeds()
        except Exception:
            log.exception("FortuneGarden bloom processor failed; it will retry on the next cycle.")

    @bloom_loop.before_loop
    async def before_bloom(self):
        await self.bot.wait_until_ready()
        await self._migrate_member_data()

    async def on_message(self, message):
        if self._resetting:
            return
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
            member_conf = self.config.user(message.author)
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

    async def fortuneseeds(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        lock = self._member_lock(ctx.guild.id, member.id)
        async with lock:
            garden = await self._get_garden(self.config.user(member))
        embed = discord.Embed(
            title="🌱 Fortune Seed Inventory",
            description=f"{member.mention} has **{garden['seeds']}** seed{'s' if garden['seeds'] != 1 else ''}.",
            color=discord.Color.random(),
        )
        for seed_type, details in SEED_TYPES.items():
            embed.add_field(name=f"{details['emoji']} {details['label']}", value=str(garden["seed_inventory"].get(seed_type, 0)), inline=True)
        embed.set_image(url=SEED_BANNER)
        await ctx.send(embed=embed)

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
                member_conf = self.config.user(ctx.author)
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
                companion = garden.get("equipped_companion")
                if companion == "fox":
                    delay_hours *= 0.95
                elif companion == "firefly":
                    delay_hours *= 0.90
                elif companion == "turtle":
                    delay_hours *= 0.92
                weather, moon = weather_and_moon(biome=garden.get("equipped_biome", "meadow"))
                weather_effect = WEATHER_EFFECTS.get(weather, {})
                delay_hours *= float(weather_effect.get("growth_multiplier", 1.0))
                if companion == "koi" and weather in ("Rainy", "Blossom Rain", "Starlit"):
                    delay_hours *= 0.90
                if seed_type == "moonlight":
                    delay_hours *= float(weather_effect.get("moonlight_multiplier", 1.0))
                if moon == "Full Moon" and seed_type == "moonlight":
                    delay_hours *= 0.90
                seen_weather = garden.setdefault("weather_seen", [])
                if weather not in seen_weather:
                    seen_weather.append(weather)
                seen_phases = garden.setdefault("moon_phases_seen", [])
                if moon not in seen_phases:
                    seen_phases.append(moon)
                boosts = garden.setdefault("active_boosts", {})
                if boosts.pop("moonlight_essence", False):
                    delay_hours *= 0.95
                now = datetime.utcnow()
                bloom_time = now + timedelta(hours=delay_hours)
                fortunes = guild_data.get("fortunes", {})
                fid = f"{ctx.guild.id}-{int(now.timestamp() * 1000)}-{random.randint(1000, 9999)}"
                while fid in fortunes:
                    fid = f"{ctx.guild.id}-{int(datetime.utcnow().timestamp() * 1000)}-{random.randint(1000, 9999)}"
                fortunes[fid] = {
                    "owner_id": ctx.author.id,
                    "channel_id": ctx.channel.id,
                    "bloom_time": bloom_time.isoformat(),
                    "processed": False,
                    "seed_type": seed_type,
                    "seed_name": name,
                    "weather": weather,
                    "moon_phase": moon,
                    "festival_key": current_festival_event(now)["key"],
                    "fertilized": False,
                    "attempts": 0,
                }
                garden["seed_inventory"][seed_type] -= 1
                garden["total_planted"] = int(garden.get("total_planted", 0)) + 1
                self._progress_quests(garden, "plant", 1)
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
                member_conf = self.config.user(owner)
                garden = await self._get_garden(member_conf)
                seed_type = info.get("seed_type", "common")
                if seed_type not in SEED_TYPES:
                    seed_type = "common"
                garden["seed_inventory"][seed_type] = garden["seed_inventory"].get(seed_type, 0) + 1
                await self._save_garden(member_conf, garden)
                fortunes.pop(fid)
                await guild_conf.fortunes.set(fortunes)
        await ctx.send(f"🗑️ Removed fortune seed `{fid}` and returned it to {owner.mention}'s inventory.")

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
                member_conf = self.config.user(ctx.author)
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
                garden["total_waterings"] = int(garden.get("total_waterings", 0)) + 1
                last_water = garden.get("last_water_date")
                yesterday = (datetime.utcnow().date() - timedelta(days=1)).isoformat()
                garden["water_streak"] = int(garden.get("water_streak", 0)) + 1 if last_water == yesterday else 1
                garden["last_water_date"] = today
                self._add_xp(garden, 5)
                self._progress_quests(garden, "water", 1)
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
                member_conf = self.config.user(ctx.author)
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

    async def show_garden_profile(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        lock = self._member_lock(ctx.guild.id, member.id)
        async with lock:
            garden = await self._get_garden(self.config.user(member))
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

    async def gardenflowers(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        lock = self._member_lock(ctx.guild.id, member.id)
        async with lock:
            garden = await self._get_garden(self.config.user(member))
        flowers = garden.get("flowers", {})
        if not flowers:
            return await ctx.send(f"{member.mention} hasn't discovered any flowers yet. Plant seeds and wait for them to bloom!")
        rarity_order = {"Legendary": 0, "Epic": 1, "Rare": 2, "Uncommon": 3, "Seasonal": 4, "Common": 5}
        lines = [f"**{FLOWERS.get(name, 'Common')}** — {name} ×{count}" for name, count in sorted(flowers.items(), key=lambda item: (rarity_order.get(FLOWERS.get(item[0], 'Common'), 9), item[0])) if count > 0]
        embed = discord.Embed(title=f"🌸 {member.display_name}'s Flower Collection", description="\n".join(lines)[:4000], color=discord.Color.random())
        embed.set_footer(text=f"{len(flowers)} unique flower varieties • {sum(flowers.values())} total flowers")
        await ctx.send(embed=embed)

    async def gardenachievements(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        lock = self._member_lock(ctx.guild.id, member.id)
        async with lock:
            garden = await self._get_garden(self.config.user(member))
        earned = set(garden.get("achievements", []))
        lines = []
        for name, description in ACHIEVEMENT_DESCRIPTIONS.items():
            reward = ACHIEVEMENT_REWARDS.get(name, {})
            rewards = []
            if reward.get("xp"):
                rewards.append(f"{reward['xp']} XP")
            rewards.extend(f"{count} {SEED_TYPES[key]['label']}" for key, count in reward.get("seeds", {}).items() if key in SEED_TYPES)
            rewards.extend(f"{count} {key.replace('_', ' ')}" for key, count in reward.get("items", {}).items())
            rewards.extend(f"{count} {RECIPES[key]['label']}" for key, count in reward.get("potions", {}).items() if key in RECIPES)
            reward_text = f" · Reward: {', '.join(rewards)}" if rewards else ""
            marker = "🏅" if name in earned else "🔒"
            lines.append(f"{marker} **{name}** — {description}{reward_text}")
        pages = []
        for start_index in range(0, len(lines), 7):
            page_lines = lines[start_index:start_index + 7]
            page_number = len(pages) + 1
            pages.append(discord.Embed(title=f"🏆 {member.display_name}'s Achievements", description="\n\n".join(page_lines), color=discord.Color.gold()).set_footer(text=f"Unlocked {len(earned)}/{len(ACHIEVEMENT_DESCRIPTIONS)} · Page {page_number}"))
        view = FortunePaginator(ctx.author.id, pages)
        if len(pages) == 1:
            return await ctx.send(embed=pages[0])
        view.message = await ctx.send(embed=pages[0], view=view)

    async def fortunehistory(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        lock = self._member_lock(ctx.guild.id, member.id)
        async with lock:
            garden = await self._get_garden(self.config.user(member))
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

    async def fortuneevent(self, ctx):
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            garden = await self._get_garden(self.config.user(ctx.author))
        seasonal = current_seasonal_event()
        seasonal_points = int(garden.get("event_progress", {}).get(seasonal["key"], 0))
        festival = current_festival_event()
        festival_points = int(garden.get("festival_progress", {}).get(festival["key"], 0))
        embed = discord.Embed(title="🎪 FortuneGarden Events", description="Take part in the long-running seasonal celebration and the rotating weekly festival. Every seed bloom contributes to both.", color=discord.Color.random())
        embed.add_field(name=f"{seasonal['emoji']} {seasonal['name']}", value=f"{seasonal.get('description', 'A seasonal celebration in your garden.') }\n**Your progress:** {seasonal_points} blooms\n**5 blooms:** {seasonal['flower']}\n**10 blooms:** Golden Seed\n**20 blooms:** Seasonal Moon Lantern", inline=False)
        embed.add_field(name=f"{festival['emoji']} {festival['name']}", value=f"{festival['description']}\n**Your progress this week:** {festival_points}/14 blooms\n**3 blooms:** {festival['flower']}\n**7 blooms:** Fortune Elixir\n**14 blooms:** Festival keepsake decoration", inline=False)
        embed.set_footer(text="Festival progress rotates every Monday; seasonal progress lasts for the full season.")
        await ctx.send(embed=embed)

    async def gardendecorate(self, ctx, *, decoration: str = "list"):
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            member_conf = self.config.user(ctx.author)
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
                return await ctx.send("You haven't unlocked that decoration. Use the FortuneGarden **Customize** menu to see your options.")
            garden["equipped_decoration"] = match
            achievements = self._check_achievements(garden)
            await self._save_garden(member_conf, garden)
        await ctx.send(f"🏡 **{match}** is now displayed in your garden." + (f"\n🏅 Unlocked: {', '.join(achievements)}" if achievements else ""))

    async def gardenquests(self, ctx):
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            garden = await self._get_garden(self.config.user(ctx.author))
            self._refresh_quests(garden)
            await self._save_garden(self.config.user(ctx.author), garden)
        lines = []
        for period, label in (("daily", "Daily"), ("weekly", "Weekly")):
            lines.append(f"**{label} quests**")
            for task in garden["quest_state"].get(period, []):
                status = "✅ Claimed" if task.get("claimed") else f"{min(task.get('progress', 0), task['target'])}/{task['target']}"
                lines.append(f"`{task['id']}` — {task['description']} ({status}) · {task['xp']} XP")
        await ctx.send(embed=discord.Embed(title="📜 Garden Quest Board", description="\n".join(lines), color=discord.Color.green()).set_footer(text="Use the FortuneGarden menu → Quests & Rankings to claim completed quests"))

    async def gardenquestclaim(self, ctx, quest_id: str):
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            member_conf = self.config.user(ctx.author)
            garden = await self._get_garden(member_conf)
            self._refresh_quests(garden)
            match = next(((period, task) for period in ("daily", "weekly") for task in garden["quest_state"].get(period, []) if task["id"] == quest_id.lower()), None)
            if not match:
                return await ctx.send("I couldn't find that quest ID. Open the FortuneGarden menu and choose **Quests** to view your current quests.")
            period, task = match
            if task.get("claimed"):
                return await ctx.send("You've already claimed that quest.")
            if int(task.get("progress", 0)) < int(task.get("target", 1)):
                return await ctx.send("That quest isn't complete yet.")
            task["claimed"] = True
            garden["total_quests_claimed"] = int(garden.get("total_quests_claimed", 0)) + 1
            self._add_xp(garden, int(task.get("xp", 0)))
            item = task.get("item")
            amount = int(task.get("amount", 1))
            if item == "fertilizer":
                garden.setdefault("items", {})["fertilizer"] = int(garden["items"].get("fertilizer", 0)) + amount
            elif item in ("common_seed", "golden_seed"):
                seed = item.replace("_seed", "")
                garden["seed_inventory"][seed] = int(garden["seed_inventory"].get(seed, 0)) + amount
            elif item in RECIPES:
                garden.setdefault("potions", {})[item] = int(garden["potions"].get(item, 0)) + amount
            achievements = self._check_achievements(garden)
            await self._save_garden(member_conf, garden)
        await ctx.send(f"🎉 Claimed **{task['description']}**! You received **{task['xp']} XP** and **{amount} {item.replace('_', ' ') if item else 'bonus'}**." + (f"\n🏅 Unlocked: {', '.join(achievements)}" if achievements else ""))

    async def gardenbrew(self, ctx, action: str = "recipes", item: str = None, seed_id: str = None):
        action = action.lower()
        if action in ("recipes", "list"):
            lines = [f"**{key} — {recipe['label']}**\n{recipe['description']}\nIngredients: " + ", ".join(f"{name} ×{count}" for name, count in recipe["ingredients"].items()) for key, recipe in RECIPES.items()]
            return await ctx.send(embed=discord.Embed(title="⚗️ Garden Alchemy", description="\n\n".join(lines), color=discord.Color.purple()))
        if action not in ("craft", "use") or not item:
            return await ctx.send("Open `{prefix}forgarden` and choose **Alchemy** to craft or use a potion.")
        item = item.lower()
        if action == "craft":
            if item not in RECIPES:
                return await ctx.send("Unknown recipe. Open the FortuneGarden menu and choose **Alchemy**.")
            lock = self._member_lock(ctx.guild.id, ctx.author.id)
            async with lock:
                member_conf = self.config.user(ctx.author)
                garden = await self._get_garden(member_conf)
                recipe = RECIPES[item]
                for flower, count in recipe["ingredients"].items():
                    if self._asset_count(garden, "flower", flower) < count:
                        return await ctx.send(f"You need **{count} {flower}** to craft {recipe['label']}.")
                for flower, count in recipe["ingredients"].items():
                    self._transfer_asset(garden, "flower", flower, count, add=False)
                garden.setdefault("potions", {})[item] = int(garden["potions"].get(item, 0)) + 1
                garden["total_crafted"] = int(garden.get("total_crafted", 0)) + 1
                self._progress_quests(garden, "craft", 1)
                self._add_xp(garden, 10)
                achievements = self._check_achievements(garden)
                await self._save_garden(member_conf, garden)
            note = f"\n🏅 Unlocked: {', '.join(achievements)}" if achievements else ""
            return await ctx.send(f"⚗️ Crafted **{recipe['label']}**! You now have {garden['potions'][item]}.{note}")
        if not seed_id:
            return await ctx.send("Use the **Alchemy** section of the FortuneGarden menu to use a potion on a growing seed.")
        if item not in RECIPES:
            return await ctx.send("Unknown potion. Open the FortuneGarden menu and choose **Alchemy**.")
        guild_lock = self._guild_lock(ctx.guild.id)
        member_lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with guild_lock:
            async with member_lock:
                guild_conf = self.config.guild(ctx.guild)
                fortunes = await guild_conf.fortunes()
                info = fortunes.get(seed_id)
                if not info or int(info.get("owner_id", 0)) != ctx.author.id or info.get("processed"):
                    return await ctx.send("That isn't one of your growing seeds.")
                member_conf = self.config.user(ctx.author)
                garden = await self._get_garden(member_conf)
                potions = garden.setdefault("potions", {})
                if int(potions.get(item, 0)) < 1:
                    return await ctx.send(f"You don't have a {RECIPES[item]['label']}.")
                try:
                    bloom_time = datetime.fromisoformat(info["bloom_time"])
                except (KeyError, ValueError, TypeError):
                    return await ctx.send("That seed has an invalid growing timer.")
                if item == "growth_potion":
                    info["bloom_time"] = max(datetime.utcnow(), bloom_time - timedelta(hours=2)).isoformat()
                elif item == "dew_of_renewal":
                    info["bloom_time"] = max(datetime.utcnow(), bloom_time - timedelta(hours=4)).isoformat()
                elif item in ("golden_fertilizer", "aurora_draught"):
                    info["fertilized"] = True
                    info["bloom_time"] = max(datetime.utcnow(), bloom_time - timedelta(minutes=30)).isoformat()
                    if item == "aurora_draught":
                        info["aurora_boost"] = True
                elif item in ("fortune_elixir", "prism_philter"):
                    info["fortune_boost"] = True
                    if item == "prism_philter":
                        info["prism_boost"] = True
                elif item == "moonlight_essence":
                    info["moonlight_boost"] = True
                elif item == "nectar_tonic":
                    info["nectar_boost"] = True
                elif item == "pollinator_charm":
                    info["pollinator_boost"] = True
                elif item == "rootbound_brew":
                    info["rootbound_boost"] = True
                elif item == "sunfire_syrup":
                    info["sunfire_boost"] = True
                elif item == "dreamweaver_elixir":
                    info["dream_boost"] = True
                elif item == "stargazer_serum":
                    info["stargazer_boost"] = True
                potions[item] = max(0, int(potions.get(item, 0)) - 1)
                await self._save_garden(member_conf, garden)
                await guild_conf.fortunes.set(fortunes)
        await ctx.send(f"✨ Used **{RECIPES[item]['label']}** on seed `{seed_id}`.")

    async def gardencompanion(self, ctx, action: str = "list", *, companion: str = None):
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            member_conf = self.config.user(ctx.author)
            garden = await self._get_garden(member_conf)
            discovered = garden.get("companions", [])
            if action.lower() == "list":
                lines = [f"{COMPANIONS[key]['emoji']} **{COMPANIONS[key]['label']}** — {COMPANIONS[key]['description']}" for key in discovered if key in COMPANIONS]
                lines.append(f"\nEquipped: **{COMPANIONS.get(garden.get('equipped_companion'), {}).get('label', 'None')}**")
                lines.append("Use the FortuneGarden menu to adopt or equip companions.")
                return await ctx.send(embed=discord.Embed(title="🐾 Garden Companions", description="\n".join(lines), color=discord.Color.green()))
            if action.lower() == "equip":
                key = (companion or "").lower().replace(" ", "_")
                aliases = {value["label"].lower().replace(" ", "_"): name for name, value in COMPANIONS.items()}
                key = aliases.get(key, key)
                if key not in discovered:
                    return await ctx.send("You haven't discovered that companion yet. Check the **Companions** section in the FortuneGarden menu.")
                garden["equipped_companion"] = key
                await self._save_garden(member_conf, garden)
                return await ctx.send(f"{COMPANIONS[key]['emoji']} **{COMPANIONS[key]['label']}** is now accompanying your garden.")
        await ctx.send("Open the FortuneGarden menu and choose **Companions**.")

    async def gardenadopt(self, ctx, companion: str):
        key = companion.lower().replace(" ", "_")
        if key not in COMPANIONS:
            return await ctx.send("Available companions: " + ", ".join(COMPANIONS))
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            member_conf = self.config.user(ctx.author)
            garden = await self._get_garden(member_conf)
            if key in garden.get("companions", []):
                return await ctx.send("You already have that companion.")
            cost = COMPANIONS[key]["cost"]
            flower, count = cost["flower"], cost["count"]
            if self._asset_count(garden, "flower", flower) < count:
                return await ctx.send(f"You need **{count} {flower}** to adopt {COMPANIONS[key]['label']}.")
            self._transfer_asset(garden, "flower", flower, count, add=False)
            garden.setdefault("companions", []).append(key)
            self._add_xp(garden, 20)
            achievements = self._check_achievements(garden)
            await self._save_garden(member_conf, garden)
        await ctx.send(f"{COMPANIONS[key]['emoji']} You adopted **{COMPANIONS[key]['label']}**! You can equip it from the **Companions** section in the FortuneGarden menu." + (f"\n🏅 Unlocked: {', '.join(achievements)}" if achievements else ""))

    async def gardenbiome(self, ctx, action: str = "list", biome: str = None):
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            member_conf = self.config.user(ctx.author)
            garden = await self._get_garden(member_conf)
            if action.lower() == "list":
                lines = []
                for key, info in BIOMES.items():
                    unlocked = key in garden.get("biomes", []) or garden.get("garden_level", 1) >= info["level"]
                    lines.append(f"{'✅' if unlocked else '🔒'} **{key} — {info['label']}** (Level {info['level']})\n{info['description']}")
                return await ctx.send(embed=discord.Embed(title="🌍 Garden Biomes", description="\n\n".join(lines), color=discord.Color.green()))
            if action.lower() not in ("set", "equip") or not biome or biome.lower() not in BIOMES:
                return await ctx.send("Open the FortuneGarden menu and choose **Explore** to change your biome.")
            key = biome.lower()
            if int(garden.get("garden_level", 1)) < BIOMES[key]["level"] and key not in garden.get("biomes", []):
                return await ctx.send(f"That biome unlocks at garden level {BIOMES[key]['level']}.")
            if key not in garden.setdefault("biomes", []):
                garden["biomes"].append(key)
            garden["equipped_biome"] = key
            achievements = self._check_achievements(garden)
            await self._save_garden(member_conf, garden)
        await ctx.send(f"🌍 Your garden biome is now **{BIOMES[key]['label']}**." + (f"\n🏅 Unlocked: {', '.join(achievements)}" if achievements else ""))

    async def gardenexpedition(self, ctx, action: str = "list", mission: str = None):
        action = action.lower()
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            member_conf = self.config.user(ctx.author)
            garden = await self._get_garden(member_conf)
            active = garden.get("expedition")
            if action == "list":
                lines = [f"**{key} — {info['label']}** · {info['hours']}h\n{info['description']}" for key, info in EXPEDITIONS.items()]
                status = "No expedition currently active."
                if active:
                    end = datetime.fromisoformat(active["end_time"])
                    remaining = max(0, int((end - datetime.utcnow()).total_seconds()))
                    status = f"Active: **{EXPEDITIONS[active['mission']]['label']}** · {remaining // 3600}h {(remaining % 3600) // 60}m remaining."
                return await ctx.send(embed=discord.Embed(title="🧭 Garden Expeditions", description="\n\n".join(lines) + "\n\n" + status, color=discord.Color.blurple()))
            if action == "start":
                key = (mission or "").lower()
                if key not in EXPEDITIONS:
                    return await ctx.send("Choose one: " + ", ".join(EXPEDITIONS))
                if active:
                    return await ctx.send("You already have an expedition underway. Collect it before starting another.")
                companion_bonus = 0.9 if garden.get("equipped_companion") == "spirit" else 1.0
                duration = EXPEDITIONS[key]["hours"] * companion_bonus
                garden["expedition"] = {"mission": key, "end_time": (datetime.utcnow() + timedelta(hours=duration)).isoformat(), "started_at": datetime.utcnow().isoformat()}
                await self._save_garden(member_conf, garden)
                return await ctx.send(f"🧭 Your expedition to **{EXPEDITIONS[key]['label']}** has begun. Return in approximately **{duration:.1f} hours** and use the FortuneGarden menu to collect it.")
            if action == "collect":
                if not active:
                    return await ctx.send("You don't have an active expedition.")
                if datetime.utcnow() < datetime.fromisoformat(active["end_time"]):
                    return await ctx.send("Your expedition is still underway. Check the **Explore** section in the FortuneGarden menu for the remaining time.")
                key = active["mission"]
                reward_lines = []
                roll = random.random()
                if key == "whispering_woods":
                    self._add_xp(garden, 35)
                    garden["seed_inventory"]["common"] += 1
                    reward_lines.extend(["35 garden XP", "1 Common Seed"])
                    companion_chance = 0.12
                elif key == "forgotten_ruins":
                    self._add_xp(garden, 65)
                    garden.setdefault("items", {})["fertilizer"] += 2
                    reward_lines.extend(["65 garden XP", "2 Fertilizer"])
                    companion_chance = 0.22
                elif key == "crystal_caverns":
                    self._add_xp(garden, 45)
                    garden.setdefault("potions", {})["growth_potion"] += 1
                    reward_lines.extend(["45 garden XP", "1 Growth Potion"])
                    companion_chance = 0.10
                elif key == "moonlit_lake":
                    self._add_xp(garden, 50)
                    flower, rarity = self._choose_flower("moonlight", current_seasonal_event(), garden.get("equipped_companion"), garden.get("equipped_biome", "meadow"))
                    self._add_flower(garden, flower)
                    self._progress_quests(garden, "flower", 1)
                    reward_lines.extend(["50 garden XP", f"{rarity} {flower}"])
                    companion_chance = 0.15
                elif key == "ember_citadel":
                    self._add_xp(garden, 85)
                    garden["seed_inventory"]["golden"] += 1
                    flower = "Emberheart Bloom"
                    self._add_flower(garden, flower)
                    garden.setdefault("potions", {})["sunfire_syrup"] = int(garden["potions"].get("sunfire_syrup", 0)) + 1
                    reward_lines.extend(["85 garden XP", "1 Golden Seed", flower, "1 Sunfire Syrup"])
                    companion_chance = 0.25
                elif key == "sunken_grotto":
                    self._add_xp(garden, 70)
                    flower = "Tideglass Lotus"
                    self._add_flower(garden, flower)
                    garden.setdefault("potions", {})["dew_of_renewal"] = int(garden["potions"].get("dew_of_renewal", 0)) + 1
                    reward_lines.extend(["70 garden XP", flower, "1 Dew of Renewal"])
                    companion_chance = 0.20
                else:
                    self._add_xp(garden, 100)
                    flower = "Dreamrose"
                    self._add_flower(garden, flower)
                    garden.setdefault("potions", {})["stargazer_serum"] = int(garden["potions"].get("stargazer_serum", 0)) + 1
                    reward_lines.extend(["100 garden XP", flower, "1 Stargazer Serum"])
                    companion_chance = 0.25
                if garden.get("equipped_companion") == "spirit":
                    companion_chance += 0.05
                if roll < companion_chance:
                    missing = [name for name in COMPANIONS if name not in garden.get("companions", [])]
                    if missing:
                        found = random.choice(missing)
                        garden.setdefault("companions", []).append(found)
                        reward_lines.append(f"Discovered {COMPANIONS[found]['label']}")
                garden["expedition"] = None
                garden["total_expeditions"] = int(garden.get("total_expeditions", 0)) + 1
                self._progress_quests(garden, "expedition", 1)
                self._add_world_tree_xp(garden, 10)
                achievements = self._check_achievements(garden)
                await self._save_garden(member_conf, garden)
                return await ctx.send("🧭 Expedition complete! You found:\n• " + "\n• ".join(reward_lines) + (f"\n🏅 Unlocked: {', '.join(achievements)}" if achievements else ""))
        await ctx.send("Open the FortuneGarden menu and choose **Explore** to manage expeditions.")

    async def gardenvisit(self, ctx, member: discord.Member, *, compliment: str = "Your garden is lovely!"):
        if member.bot or member.id == ctx.author.id:
            return await ctx.send("Choose another human member's garden to visit.")
        ordered_ids = sorted((member.id, ctx.author.id))
        first = self._member_lock(ctx.guild.id, ordered_ids[0])
        second = self._member_lock(ctx.guild.id, ordered_ids[1])
        async with first:
            async with second:
                owner_conf = self.config.user(member)
                owner_garden = await self._get_garden(owner_conf)
                visitor_conf = self.config.user(ctx.author)
                visitor_garden = await self._get_garden(visitor_conf)
                today = datetime.utcnow().date().isoformat()
                if visitor_garden.setdefault("last_visits", {}).get(str(member.id)) == today:
                    return await ctx.send("You've already visited this garden today.")
                visitor_garden["last_visits"][str(member.id)] = today
                visitor_garden["total_visits_made"] = int(visitor_garden.get("total_visits_made", 0)) + 1
                owner_garden["visit_count"] = int(owner_garden.get("visit_count", 0)) + 1
                owner_garden.setdefault("guestbook", []).append({"visitor_id": ctx.author.id, "message": discord.utils.escape_mentions(compliment[:160]), "timestamp": datetime.utcnow().isoformat()})
                owner_garden["guestbook"] = owner_garden["guestbook"][-20:]
                self._progress_quests(visitor_garden, "visit", 1)
                self._add_xp(visitor_garden, 5)
                visitor_achievements = self._check_achievements(visitor_garden)
                owner_achievements = self._check_achievements(owner_garden)
                await self._save_garden(owner_conf, owner_garden)
                await self._save_garden(visitor_conf, visitor_garden)
        biome = owner_garden.get("equipped_biome", "meadow")
        companion = COMPANIONS.get(owner_garden.get("equipped_companion"), {})
        summary = (f"**Level:** {owner_garden.get('garden_level', 1)} · **Prestige:** {owner_garden.get('prestige', 0)}\n"
                   f"**Biome:** {BIOMES.get(biome, BIOMES['meadow'])['label']}\n"
                   f"**Flowers:** {sum(owner_garden.get('flowers', {}).values())} · **Unique:** {len([v for v in owner_garden.get('flowers', {}).values() if v > 0])}\n"
                   f"**Companion:** {companion.get('label', 'None')}\n"
                   f"**Decoration:** {owner_garden.get('equipped_decoration') or 'None'}\n"
                   f"🌷 **Visits:** {owner_garden['visit_count']}\n\n{discord.utils.escape_mentions(compliment[:160])}")
        await ctx.send(embed=discord.Embed(title=f"🏡 Visiting {member.display_name}'s Garden", description=summary, color=discord.Color.green()))

    async def gardenguestbook(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        garden = await self._get_garden(self.config.user(member))
        entries = garden.get("guestbook", [])[-10:]
        if not entries:
            return await ctx.send(f"{member.display_name}'s garden guestbook is empty.")
        lines = []
        for entry in reversed(entries):
            visitor = ctx.guild.get_member(int(entry.get("visitor_id", 0)))
            label = visitor.display_name if visitor else f"Visitor {entry.get('visitor_id')}"
            lines.append(f"**{discord.utils.escape_markdown(label)}**: {entry.get('message', '')}")
        await ctx.send(embed=discord.Embed(title=f"📖 {member.display_name}'s Guestbook", description="\n".join(lines)[:4000], color=discord.Color.green()))

    async def gardengift(self, ctx, member: discord.Member, *, flower: str):
        if member.bot or member.id == ctx.author.id:
            return await ctx.send("Choose another human member.")
        ordered_ids = sorted((ctx.author.id, member.id))
        first = self._member_lock(ctx.guild.id, ordered_ids[0])
        second = self._member_lock(ctx.guild.id, ordered_ids[1])
        async with first:
            async with second:
                sender_conf = self.config.user(ctx.author)
                receiver_conf = self.config.user(member)
                sender = await self._get_garden(sender_conf)
                receiver = await self._get_garden(receiver_conf)
                today = datetime.utcnow().date().isoformat()
                if sender.setdefault("last_visit_gifts", {}).get(str(member.id)) == today:
                    return await ctx.send("You've already given this member a garden gift today.")
                found = next((name for name in sender.get("flowers", {}) if name.lower() == flower.lower()), None)
                if not found or int(sender["flowers"].get(found, 0)) < 1:
                    return await ctx.send("You don't have that flower to give.")
                sender["flowers"][found] -= 1
                sender["total_gifts_sent"] = int(sender.get("total_gifts_sent", 0)) + 1
                receiver.setdefault("flowers", {})[found] = int(receiver["flowers"].get(found, 0)) + 1
                sender["last_visit_gifts"][str(member.id)] = today
                self._progress_quests(sender, "gift", 1)
                self._progress_quests(receiver, "gift", 1)
                self._add_xp(receiver, 5)
                sender_achievements = self._check_achievements(sender)
                receiver_achievements = self._check_achievements(receiver)
                await self._save_garden(sender_conf, sender)
                await self._save_garden(receiver_conf, receiver)
        await ctx.send(f"🎁 {ctx.author.mention} gifted **{found}** to {member.mention}!")

    async def gardenhelpwater(self, ctx, member: discord.Member, seed_id: str):
        if member.bot or member.id == ctx.author.id:
            return await ctx.send("Choose another member's growing seed.")
        guild_lock = self._guild_lock(ctx.guild.id)
        async with guild_lock:
            guild_conf = self.config.guild(ctx.guild)
            fortunes = await guild_conf.fortunes()
            info = fortunes.get(seed_id)
            if not info or int(info.get("owner_id", 0)) != member.id or info.get("processed"):
                return await ctx.send("That isn't one of this member's growing seeds in this server.")
            today = datetime.utcnow().date().isoformat()
            key = str(ctx.author.id)
            watered = info.setdefault("helped_by", {})
            if watered.get(key) == today:
                return await ctx.send("You've already helped water this seed today.")
            bloom_time = datetime.fromisoformat(info["bloom_time"])
            info["bloom_time"] = max(datetime.utcnow(), bloom_time - timedelta(minutes=15)).isoformat()
            watered[key] = today
            await guild_conf.fortunes.set(fortunes)
        helper_conf = self.config.user(ctx.author)
        helper_lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with helper_lock:
            helper_garden = await self._get_garden(helper_conf)
            self._progress_quests(helper_garden, "water", 1)
            self._add_xp(helper_garden, 3)
            await self._save_garden(helper_conf, helper_garden)
        await ctx.send(f"💧 You helped {member.mention} water their seed and reduced its growing time by 15 minutes! You earned 3 garden XP.")

    def _market_stock(self, now=None):
        day = (now or datetime.utcnow()).date().isoformat()
        keys = list(MARKET_ITEMS)
        return random.Random(day).sample(keys, 4)

    async def gardenmarket(self, ctx):
        day = datetime.utcnow().date().isoformat()
        currency = await bank.get_currency_name(ctx.guild)
        stock = self._market_stock()
        lines = [f"**{key}** — {MARKET_ITEMS[key]['label']} · **{MARKET_ITEMS[key]['price']} {currency}**\n{MARKET_ITEMS[key]['description']}" for key in stock]
        embed = discord.Embed(title="🛍️ Garden Supply Market", description="\n\n".join(lines), color=discord.Color.gold())
        embed.set_footer(text=f"Prices shown for {day}. Use the FortuneGarden menu → Market & Community to purchase supplies.")
        await ctx.send(embed=embed)

    async def gardenbuy(self, ctx, item: str, amount: int = 1):
        item = item.lower()
        if item not in MARKET_ITEMS or item not in self._market_stock() or amount < 1 or amount > 25:
            return await ctx.send("That item isn't in today's rotating stock. Open the FortuneGarden menu → Market & Community to see available stock. Purchase between 1 and 25 at a time.")
        total = MARKET_ITEMS[item]["price"] * amount
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            member_conf = self.config.user(ctx.author)
            garden = await self._get_garden(member_conf)
            try:
                await bank.withdraw_credits(ctx.author, total)
            except Exception as exc:
                return await ctx.send(f"The purchase couldn't be completed: {exc}")
            if item == "fertilizer":
                garden.setdefault("items", {})["fertilizer"] = int(garden["items"].get("fertilizer", 0)) + amount
            elif item.endswith("_seed"):
                seed = item.replace("_seed", "")
                garden["seed_inventory"][seed] = int(garden["seed_inventory"].get(seed, 0)) + amount
            else:
                garden.setdefault("potions", {})[item] = int(garden["potions"].get(item, 0)) + amount
            garden["total_items_purchased"] = int(garden.get("total_items_purchased", 0)) + amount
            achievements = self._check_achievements(garden)
            await self._save_garden(member_conf, garden)
        currency = await bank.get_currency_name(ctx.guild)
        await ctx.send(f"🛍️ Purchased **{amount} × {MARKET_ITEMS[item]['label']}** for **{total} {currency}**." + (f"\n🏅 Unlocked: {', '.join(achievements)}" if achievements else ""))

    async def gardenoffer(self, ctx, member: discord.Member, give_type: str, give_item: str, want_type: str, want_item: str, amount: int = 1):
        give_type, want_type = give_type.lower(), want_type.lower()
        give_item, want_item = give_item.lower(), want_item.lower()
        if member.bot or member.id == ctx.author.id or amount < 1 or amount > 100:
            return await ctx.send("Choose another human member and an amount between 1 and 100.")
        if give_type not in ("seed", "flower", "item") or want_type not in ("seed", "flower", "item"):
            return await ctx.send("Trade types must be `seed`, `flower` or `item`.")
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            garden = await self._get_garden(self.config.user(ctx.author))
            if self._asset_count(garden, give_type, give_item) < amount:
                return await ctx.send("You don't have enough of the item you're offering.")
        guild_lock = self._guild_lock(ctx.guild.id)
        async with guild_lock:
            guild_conf = self.config.guild(ctx.guild)
            offers = await guild_conf.trade_offers()
            offer_id = f"{int(datetime.utcnow().timestamp())}-{random.randint(1000, 9999)}"
            offers[offer_id] = {"from": ctx.author.id, "to": member.id, "give": {"type": give_type, "item": give_item, "amount": amount}, "want": {"type": want_type, "item": want_item, "amount": amount}, "created": datetime.utcnow().isoformat(), "status": "pending"}
            await guild_conf.trade_offers.set(offers)
        await ctx.send(f"🤝 Trade offer `{offer_id}` sent to {member.mention}. They can accept or decline from the FortuneGarden **Social** menu. Both sides exchange **{amount}** item(s).")

    async def gardentrade(self, ctx, offer_id: str, decision: str):
        decision = decision.lower()
        if decision not in ("accept", "decline"):
            return await ctx.send("Use the **Respond to Trade** button in the Social section of the FortuneGarden menu.")
        guild_lock = self._guild_lock(ctx.guild.id)
        async with guild_lock:
            guild_conf = self.config.guild(ctx.guild)
            offers = await guild_conf.trade_offers()
            offer = offers.get(offer_id)
            if not offer or offer.get("status") != "pending":
                return await ctx.send("That trade offer is missing or no longer active.")
            if int(offer.get("to", 0)) != ctx.author.id:
                return await ctx.send("Only the intended recipient can respond to this offer.")
            created = datetime.fromisoformat(offer["created"])
            if datetime.utcnow() - created > timedelta(days=2):
                offer["status"] = "expired"
                await guild_conf.trade_offers.set(offers)
                return await ctx.send("That trade offer has expired.")
            if decision == "decline":
                offer["status"] = "declined"
                await guild_conf.trade_offers.set(offers)
                return await ctx.send("Trade offer declined.")
            sender = await self._resolve_member(ctx.guild, offer["from"])
            if sender is None:
                return await ctx.send("The person who made this offer is no longer in the server.")
            ids = sorted((sender.id, ctx.author.id))
            locks = [self._member_lock(ctx.guild.id, uid) for uid in ids]
            async with locks[0]:
                async with locks[1]:
                    sender_conf = self.config.user(sender)
                    receiver_conf = self.config.user(ctx.author)
                    sender_garden = await self._get_garden(sender_conf)
                    receiver_garden = await self._get_garden(receiver_conf)
                    give, want = offer["give"], offer["want"]
                    try:
                        self._transfer_asset(sender_garden, give["type"], give["item"], int(give["amount"]), add=False)
                        self._transfer_asset(receiver_garden, want["type"], want["item"], int(want["amount"]), add=False)
                        self._transfer_asset(sender_garden, want["type"], want["item"], int(want["amount"]), add=True)
                        self._transfer_asset(receiver_garden, give["type"], give["item"], int(give["amount"]), add=True)
                    except ValueError as exc:
                        return await ctx.send(f"Trade couldn't complete: {exc}")
                    sender_garden["total_trades_completed"] = int(sender_garden.get("total_trades_completed", 0)) + 1
                    receiver_garden["total_trades_completed"] = int(receiver_garden.get("total_trades_completed", 0)) + 1
                    self._progress_quests(sender_garden, "trade", 1)
                    self._progress_quests(receiver_garden, "trade", 1)
                    self._check_achievements(sender_garden)
                    self._check_achievements(receiver_garden)
                    await self._save_garden(sender_conf, sender_garden)
                    await self._save_garden(receiver_conf, receiver_garden)
                    offer["status"] = "accepted"
                    offer["completed"] = datetime.utcnow().isoformat()
                    await guild_conf.trade_offers.set(offers)
        await ctx.send(f"🤝 Trade `{offer_id}` completed between {sender.mention} and {ctx.author.mention}!")

    async def worldtree(self, ctx, action: str = "view", *, flower: str = None):
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            member_conf = self.config.user(ctx.author)
            garden = await self._get_garden(member_conf)
            if action.lower() in ("view", "info"):
                level = int(garden.get("world_tree_level", 1))
                xp = int(garden.get("world_tree_xp", 0))
                return await ctx.send(embed=discord.Embed(title="🌳 Your World Tree", description=f"**Level {level}** · {xp % 100}/100 growth XP\nYour tree gains a little experience whenever your seeds bloom. Nourish it with a flower from the FortuneGarden **Garden** menu.", color=discord.Color.green()))
            if action.lower() != "nourish" or not flower:
                return await ctx.send("Open the FortuneGarden menu and choose **Garden** to nourish your tree.")
            found = next((name for name in garden.get("flowers", {}) if name.lower() == flower.lower()), None)
            if not found or int(garden["flowers"].get(found, 0)) < 1:
                return await ctx.send("You don't have that flower to nourish the tree.")
            garden["flowers"][found] -= 1
            self._add_world_tree_xp(garden, 25)
            achievements = self._check_achievements(garden)
            await self._save_garden(member_conf, garden)
        await ctx.send(f"🌳 Your World Tree absorbed **{found}** and gained 25 growth XP. It is now level **{garden['world_tree_level']}**." + (f"\n🏅 Unlocked: {', '.join(achievements)}" if achievements else ""))

    async def gardencommunity(self, ctx):
        data = await self.config.guild(ctx.guild).community_garden()
        xp = int(data.get("xp", 0))
        level = 1 + xp // 250
        contributions = sorted(data.get("contributions", {}).items(), key=lambda item: int(item[1]), reverse=True)[:5]
        top = []
        for uid, score in contributions:
            member = ctx.guild.get_member(int(uid))
            top.append(f"{member.display_name if member else uid}: {score}")
        embed = discord.Embed(title=f"🌳 {ctx.guild.name}'s Community Garden", description=f"**Level {level}** · {xp % 250}/250 toward the next level\n**Total growth:** {xp} community points\n**Your contributions:** {data.get('contributions', {}).get(str(ctx.author.id), 0)}", color=discord.Color.green())
        embed.add_field(name="Top Contributors", value="\n".join(top) if top else "No contributions yet.", inline=False)
        embed.set_footer(text="Use the FortuneGarden menu → Market & Community to contribute.")
        await ctx.send(embed=embed)

    async def gardencontribute(self, ctx, kind: str, item: str, amount: int = 1):
        kind = kind.lower()
        amount = int(amount)
        if amount < 1 or amount > 100000:
            return await ctx.send("Contribution amount must be between 1 and 100,000.")
        if kind not in ("flower", "seed", "credits"):
            return await ctx.send("Use the FortuneGarden menu → Market & Community to contribute.")
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            member_conf = self.config.user(ctx.author)
            garden = await self._get_garden(member_conf)
            if kind == "credits":
                try:
                    amount = int(item)
                except ValueError:
                    return await ctx.send("For a credit contribution, choose **credits** and enter the amount in the item field.")
                if amount < 1 or amount > 100000:
                    return await ctx.send("Credit contribution must be between 1 and 100,000.")
                try:
                    await bank.withdraw_credits(ctx.author, amount)
                except Exception as exc:
                    return await ctx.send(f"Contribution failed: {exc}")
            else:
                if amount < 1:
                    return await ctx.send("Amount must be positive.")
                asset_type = kind
                item = item.lower()
                try:
                    self._transfer_asset(garden, asset_type, item, amount, add=False)
                except ValueError as exc:
                    return await ctx.send(str(exc))
            await self._save_garden(member_conf, garden)
        points = amount * (5 if kind == "flower" else 10 if kind == "seed" else 1)
        async with lock:
            garden = await self._get_garden(self.config.user(ctx.author))
            garden["total_community_points"] = int(garden.get("total_community_points", 0)) + points
            self._progress_quests(garden, "community", 1)
            achievements = self._check_achievements(garden)
            await self._save_garden(self.config.user(ctx.author), garden)
        guild_lock = self._guild_lock(ctx.guild.id)
        async with guild_lock:
            guild_conf = self.config.guild(ctx.guild)
            data = await guild_conf.community_garden()
            data["xp"] = int(data.get("xp", 0)) + points
            data["level"] = 1 + data["xp"] // 250
            data.setdefault("contributions", {})[str(ctx.author.id)] = int(data["contributions"].get(str(ctx.author.id), 0)) + points
            await guild_conf.community_garden.set(data)
        await ctx.send(f"🌱 Thank you for contributing! The community garden gained **{points}** growth points and is now level **{data['level']}**." + (f"\n🏅 Unlocked: {', '.join(achievements)}" if achievements else ""))

    async def gardencommunityclaim(self, ctx):
        data = await self.config.guild(ctx.guild).community_garden()
        level = int(data.get("level", 1))
        if level < 2:
            return await ctx.send("The community garden needs to reach level 2 before milestone rewards unlock.")
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            member_conf = self.config.user(ctx.author)
            garden = await self._get_garden(member_conf)
            all_claims = garden.setdefault("community_claims", {})
            if isinstance(all_claims, list):
                all_claims = {}
                garden["community_claims"] = all_claims
            claims = set(int(value) for value in all_claims.get(str(ctx.guild.id), []))
            available = [value for value in range(2, level + 1) if value not in claims]
            if not available:
                return await ctx.send("You've already claimed every community garden milestone currently available.")
            for milestone in available:
                all_claims.setdefault(str(ctx.guild.id), []).append(milestone)
                garden["seed_inventory"]["common"] += 1
                garden.setdefault("items", {})["fertilizer"] += 1
            await self._save_garden(member_conf, garden)
        await ctx.send(f"🎉 Claimed **{len(available)}** community milestones! You received {len(available)} Common Seed(s) and {len(available)} Fertilizer.")

    async def gardenjournal(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        garden = await self._get_garden(self.config.user(member))
        flowers = garden.get("flowers", {})
        rarity_order = {"Common": 0, "Uncommon": 1, "Rare": 2, "Epic": 3, "Legendary": 4, "Seasonal": 5}
        lines = []
        for name, rarity in sorted(FLOWERS.items(), key=lambda item: (rarity_order.get(item[1], 9), item[0])):
            count = int(flowers.get(name, 0))
            lines.append(f"{'🌸' if count else '🔒'} **{name}** · {rarity}" + (f" ×{count}" if count else " · Not discovered"))
        pages = []
        for start in range(0, len(lines), 12):
            pages.append(discord.Embed(title=f"📖 {member.display_name}'s Botanical Journal", description="\n".join(lines[start:start + 12]), color=discord.Color.green()))
        if len(pages) == 1:
            return await ctx.send(embed=pages[0])
        view = FortunePaginator(ctx.author.id, pages)
        view.message = await ctx.send(embed=pages[0], view=view)

    async def gardendesign(self, ctx, category: str = "list", *, choice: str = None):
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            member_conf = self.config.user(ctx.author)
            garden = await self._get_garden(member_conf)
            if category.lower() == "list":
                design = garden.get("design", {})
                lines = [f"**{kind.title()}**: {', '.join(options)}\nEquipped: {design.get(kind, 'default')}" for kind, options in DESIGN_OPTIONS.items()]
                return await ctx.send(embed=discord.Embed(title="🎨 Garden Design Studio", description="\n\n".join(lines) + "\n\nUse the FortuneGarden **Customize** menu to change these settings.", color=discord.Color.blurple()))
            category = category.lower()
            if category not in DESIGN_OPTIONS or not choice:
                return await ctx.send("Open the FortuneGarden menu and choose **Customize**.")
            key = choice.lower()
            if key not in DESIGN_OPTIONS[category]:
                return await ctx.send(f"Available {category} choices: {', '.join(DESIGN_OPTIONS[category])}.")
            garden.setdefault("design", {})[category] = key
            await self._save_garden(member_conf, garden)
        await ctx.send(f"🎨 Your garden {category} is now **{DESIGN_OPTIONS[category][key]}**.")

    async def gardenleaderboard(self, ctx, category: str = "level"):
        category = category.lower()
        event = current_seasonal_event()
        ranked = []
        for member in ctx.guild.members:
            if member.bot:
                continue
            garden = await self._get_garden(self.config.user(member))
            if category == "seasonal":
                score = int(garden.get("event_progress", {}).get(event["key"], 0))
                label = f"{score} seasonal blooms"
            elif category == "flowers":
                score = sum(int(value) for value in garden.get("flowers", {}).values())
                label = f"{score} flowers"
            elif category == "festival":
                festival = current_festival_event()
                score = int(garden.get("festival_progress", {}).get(festival["key"], 0))
                label = f"{score} {festival['name']} blooms"
            else:
                score = int(garden.get("garden_level", 1))
                label = f"Level {score}"
            ranked.append((score, member.display_name, label))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if not ranked:
            return await ctx.send("There are no member gardens to rank yet.")
        title = "Seasonal Garden Leaderboard" if category == "seasonal" else "Festival Garden Leaderboard" if category == "festival" else "Flower Collection Leaderboard" if category == "flowers" else "Garden Level Leaderboard"
        lines = [f"**{index}. {discord.utils.escape_markdown(name)}** — {label}" for index, (_, name, label) in enumerate(ranked[:10], 1)]
        await ctx.send(embed=discord.Embed(title=f"🏆 {title}", description="\n".join(lines), color=discord.Color.gold()))

    async def gardenweather(self, ctx):
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            garden = await self._get_garden(self.config.user(ctx.author))
        biome_key = garden.get("equipped_biome", "meadow")
        biome = BIOMES.get(biome_key, BIOMES["meadow"])
        weather, moon = weather_and_moon(biome=biome_key)
        effect = WEATHER_EFFECTS.get(weather, {})
        description = effect.get("description", "The garden is calm today.")
        if moon == "Full Moon":
            description += " Full Moon also makes Moonlight Seeds grow 10% faster."
        elif moon == "New Moon":
            description += " New Moon favours mysterious and moonlit discoveries."
        growth_bonus = int(round((1.0 - float(effect.get("growth_multiplier", 1.0))) * 100))
        flower_bonus = int(round((float(effect.get("flower_bonus", 1.0)) - 1.0) * 100))
        embed = discord.Embed(
            title="🌦️ Garden Weather & Moon",
            description=f"**Biome:** {biome['label']}\n**Weather:** {weather}\n**Moon phase:** {moon}\n\n{description}",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="🌱 Growth Speed", value=f"{growth_bonus:+d}%", inline=True)
        embed.add_field(name="🌸 Flower Chances", value=f"{flower_bonus:+d}%", inline=True)
        embed.add_field(name="⭐ Bloom XP", value=f"+{int(effect.get('xp_bonus', 0))} XP", inline=True)
        if effect.get("special_flower"):
            embed.add_field(name="✨ Weather Flower", value=f"{effect['special_flower']} may appear during this weather.", inline=False)
        if effect.get("bonus_fertilizer_chance"):
            chance = int(round(float(effect["bonus_fertilizer_chance"]) * 100))
            embed.add_field(name="🌿 Extra Supplies", value=f"{chance}% chance to find bonus Fertilizer when a seed blooms.", inline=False)
        festival = current_festival_event()
        festival_points = int(garden.get("festival_progress", {}).get(festival["key"], 0))
        embed.add_field(name="🎪 Weekly Festival", value=f"{festival['emoji']} **{festival['name']}**\n{festival['description']}\nProgress: **{festival_points}/14 blooms** · Featured flower: **{festival['flower']}**", inline=False)
        embed.set_footer(text="Weather and moon conditions are recorded when you plant a seed and influence that seed's next bloom.")
        await ctx.send(embed=embed)

    async def gardenprestige(self, ctx, confirm: str = ""):
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            member_conf = self.config.user(ctx.author)
            garden = await self._get_garden(member_conf)
            if int(garden.get("garden_level", 1)) < 20:
                return await ctx.send("Garden prestige unlocks at level 20.")
            if confirm.lower() != "confirm":
                return await ctx.send("Prestige resets your current garden level and XP, but keeps flowers, seeds, companions, biomes, decorations and other collections. It grants an Ancient Seed, 3 Fertilizer and a permanent 1% XP bonus. Use the Prestige button in the FortuneGarden menu and type PRESTIGE to confirm.")
            garden["prestige"] = int(garden.get("prestige", 0)) + 1
            garden["permanent_xp_bonus"] = min(50, int(garden.get("permanent_xp_bonus", 0)) + 1)
            garden["garden_xp"] = 0
            garden["garden_level"] = 1
            garden["seed_inventory"]["ancient"] = int(garden["seed_inventory"].get("ancient", 0)) + 1
            garden.setdefault("items", {})["fertilizer"] = int(garden["items"].get("fertilizer", 0)) + 3
            if "Prestige Blossom" not in garden.setdefault("unlocked_decorations", []):
                garden["unlocked_decorations"].append("Prestige Blossom")
            garden["equipped_decoration"] = "Prestige Blossom"
            achievements = self._check_achievements(garden)
            await self._save_garden(member_conf, garden)
        await ctx.send(f"🌟 Your garden reached prestige **{garden['prestige']}**! You earned an Ancient Seed, 3 Fertilizer and a permanent +{garden['permanent_xp_bonus']}% XP bonus." + (f"\n🏅 Unlocked: {', '.join(achievements)}" if achievements else ""))

    async def gardenbirthday(self, ctx, action: str = "claim", date_text: str = None):
        action = action.lower()
        lock = self._member_lock(ctx.guild.id, ctx.author.id)
        async with lock:
            member_conf = self.config.user(ctx.author)
            garden = await self._get_garden(member_conf)
            if action == "set":
                if not date_text:
                    return await ctx.send("Use the **Set Birthday** button in the My Garden menu and enter MM-DD (for example, 04-21).")
                try:
                    parsed = datetime.strptime(f"{date_text}-2000", "%m-%d-%Y")
                except ValueError:
                    return await ctx.send("Use a valid month and day in MM-DD format.")
                garden["birthday"] = parsed.strftime("%m-%d")
                await self._save_garden(member_conf, garden)
                return await ctx.send(f"🎂 Birthday saved as **{garden['birthday']}**. This is optional and stored with your global garden profile.")
            if action != "claim":
                return await ctx.send("Use the **Set Birthday** or **Claim Birthday Gift** buttons in the My Garden menu.")
            today = datetime.utcnow()
            if garden.get("birthday") != today.strftime("%m-%d"):
                return await ctx.send("Today isn't your saved birthday. Set your date with the **Set Birthday** button in the My Garden menu if you would like to use this feature.")
            if int(garden.get("birthday_claimed_year") or 0) == today.year:
                return await ctx.send("You've already claimed this year's birthday gift.")
            garden["birthday_claimed_year"] = today.year
            garden["seed_inventory"]["golden"] = int(garden["seed_inventory"].get("golden", 0)) + 1
            garden.setdefault("items", {})["fertilizer"] = int(garden["items"].get("fertilizer", 0)) + 2
            self._add_xp(garden, 50)
            await self._save_garden(member_conf, garden)
        await ctx.send("🎂 Happy Birthday! Your garden gift is **1 Golden Seed**, **2 Fertilizer** and **50 garden XP**!")

    async def gardenrender(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        lock = self._member_lock(ctx.guild.id, member.id)
        async with lock:
            garden = await self._get_garden(self.config.user(member))
        try:
            import io
            from PIL import Image, ImageDraw, ImageFont
            width, height = 1000, 620
            biome = garden.get("equipped_biome", "meadow")
            backgrounds = {"sunrise": (255, 219, 170), "emerald": (31, 92, 62), "twilight": (48, 48, 91), "starlight": (24, 32, 68)}
            bg = backgrounds.get(garden.get("design", {}).get("background", "emerald"), (31, 92, 62))
            palettes = {
                "meadow": (76, 145, 80),
                "moonlit": (73, 91, 132),
                "frozen": (135, 190, 213),
                "celestial": (77, 70, 130),
                "ruins": (111, 116, 77),
                "enchanted": (49, 115, 75),
                "volcanic": (142, 76, 55),
                "tidal": (65, 132, 148),
            }
            grass = palettes.get(biome, palettes["meadow"])
            image = Image.new("RGB", (width, height), bg)
            draw = ImageDraw.Draw(image)
            font = ImageFont.load_default()
            draw.rounded_rectangle((28, 28, 972, 592), radius=30, fill=grass, outline=(225, 226, 185), width=5)
            title = f"{member.display_name}'s {BIOMES.get(biome, BIOMES['meadow'])['label']}"
            draw.text((55, 48), title[:64], fill=(255, 255, 255), font=font)
            draw.text((55, 72), f"Level {garden.get('garden_level', 1)}  |  Prestige {garden.get('prestige', 0)}  |  {garden.get('equipped_decoration') or 'Growing Garden'}", fill=(245, 245, 220), font=font)
            companion_label = COMPANIONS.get(garden.get("equipped_companion"), {}).get("label", "No companion")
            draw.text((55, 96), f"Companion: {companion_label}", fill=(245, 245, 220), font=font)
            if biome == "enchanted":
                for x in (105, 855):
                    draw.rectangle((x, 132, x + 24, 245), fill=(76, 61, 43))
                    draw.ellipse((x - 42, 105, x + 66, 205), fill=(39, 91, 60), outline=(130, 190, 120), width=3)
                for x, y in ((220, 155), (745, 175), (875, 280), (130, 430)):
                    draw.ellipse((x, y, x + 9, y + 9), fill=(245, 230, 130))
            elif biome == "volcanic":
                for points in (
                    [(75, 280), (155, 315), (130, 355), (195, 395)],
                    [(820, 250), (760, 305), (840, 360), (785, 430)],
                    [(330, 500), (380, 465), (410, 520), (455, 490)],
                ):
                    draw.line(points, fill=(242, 130, 57), width=8)
                    draw.line(points, fill=(255, 205, 105), width=3)
            elif biome == "tidal":
                for bounds in ((65, 300, 235, 395), (765, 150, 930, 245), (760, 430, 925, 520)):
                    draw.ellipse(bounds, fill=(48, 112, 142), outline=(151, 220, 225), width=4)
                    x1, y1, x2, y2 = bounds
                    draw.arc((x1 + 25, y1 + 20, x2 - 25, y2 - 20), 15, 165, fill=(190, 235, 235), width=3)
            layout = garden.get("design", {}).get("layout", "cottage")
            path_color = {"stone": (184, 180, 160), "moss": (86, 116, 72), "crystal": (155, 214, 232), "wood": (133, 88, 55)}.get(garden.get("design", {}).get("path", "stone"), (184, 180, 160))
            draw.polygon([(470, 570), (530, 570), (650, 240), (350, 240)], fill=path_color)
            flower_names = [name for name, count in garden.get("flowers", {}).items() for _ in range(min(3, int(count)))][:36]
            flower_colors = [(245, 210, 95), (220, 130, 190), (170, 205, 245), (250, 240, 220), (185, 130, 235), (240, 120, 95)]
            plots = []
            for row in range(3):
                for col in range(6):
                    x = 95 + col * 135 + (row % 2) * 18
                    y = 190 + row * 115
                    plots.append((x, y))
            if layout == "formal":
                draw.rectangle((70, 145, 930, 555), outline=(245, 235, 190), width=4)
                draw.line((500, 145, 500, 555), fill=path_color, width=18)
            elif layout == "zen":
                draw.ellipse((390, 250, 610, 470), fill=(170, 195, 180), outline=(230, 230, 210), width=5)
                draw.ellipse((430, 290, 570, 430), fill=(68, 132, 155))
            elif layout == "wild":
                for _ in range(35):
                    x, y = random.randint(70, 920), random.randint(145, 550)
                    draw.ellipse((x, y, x + 8, y + 8), fill=(190, 215, 140))
            for index, name in enumerate(flower_names):
                x, y = plots[index % len(plots)]
                color = flower_colors[index % len(flower_colors)]
                draw.line((x + 14, y + 25, x + 14, y + 58), fill=(34, 80, 42), width=4)
                draw.ellipse((x + 3, y + 4, x + 25, y + 26), fill=color, outline=(255, 255, 230), width=2)
                draw.ellipse((x + 8, y + 9, x + 20, y + 21), fill=(245, 220, 105))
                draw.text((x - 8, y + 62), name[:14], fill=(255, 255, 255), font=font)
            if not flower_names:
                draw.text((365, 350), "Your first flowers will bloom here!", fill=(255, 255, 255), font=font)
            draw.text((55, 558), f"Flowers: {sum(garden.get('flowers', {}).values())}  |  Visitors: {garden.get('visit_count', 0)}  |  World Tree: Lv. {garden.get('world_tree_level', 1)}", fill=(255, 255, 255), font=font)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            buffer.seek(0)
            await ctx.send(file=discord.File(buffer, filename="fortunegarden.png"))
        except ImportError:
            await ctx.send("Garden rendering requires Pillow. Install it in the Redbot environment with `pip install Pillow`.")
        except Exception as exc:
            log.exception("Could not render FortuneGarden for %s", member.id)
            await ctx.send(f"Could not render this garden: {exc}")

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

    async def seedopt(self, ctx, choice: str = None):
        member_conf = self.config.user(ctx.author)
        current = await member_conf.opt_out()
        choice = (choice or "help").lower()
        if choice in ("help", "h"):
            return await ctx.send("**Seed Preferences**\nUse the More section of the FortuneGarden menu to opt in, opt out or check your status.")
        if choice in ("off", "false", "optout", "out"):
            await member_conf.opt_out.set(True)
            return await ctx.send("🚫 You have opted out of receiving fortune seeds.")
        if choice in ("on", "true", "optin", "in"):
            await member_conf.opt_out.set(False)
            return await ctx.send("✅ You have opted in to receiving fortune seeds.")
        if choice == "status":
            return await ctx.send(f"ℹ️ You are currently **{'opted out' if current else 'opted in'}** of receiving seeds.")
        await ctx.send("⚠️ Open the FortuneGarden menu and choose **More** for seed preferences.")

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
        embed.add_field(name="Profile Storage", value="Seeds, cooldowns, flowers, companions, quests and personal gardens are shared globally across servers. Community gardens, seed-drop settings and trade offers are server-specific.", inline=False)
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

    @commands.is_owner()
    @commands.command(name="fortunereset", help="Reset every FortuneGarden user profile and all shared game progress. Bot owner only; requires confirmation.")
    async def fortunereset(self, ctx, confirmation: str = None):
        if (confirmation or "").lower() != "confirm":
            users = await self.config.all_users()
            legacy = await self.config.all_members()
            guilds = await self.config.all_guilds()
            profile_ids = {str(user_id) for user_id in users}
            for members in legacy.values():
                profile_ids.update(str(user_id) for user_id in members)
            embed = discord.Embed(
                title="⚠️ Reset All FortuneGarden Profiles",
                description=(
                    "This is a **global, irreversible reset**. It will erase every player's FortuneGarden profile across all servers, "
                    "including seeds, planted seeds, flowers, items, potions, companions, quests, achievements, collections, "
                    "garden levels, World Trees, prestige, birthdays, history and personal settings. It will also reset "
                    "server community gardens and remove pending trade offers.\n\n"
                    "Server configuration such as reward settings, channels, drop rates, ignored roles and custom discovery messages "
                    "will be preserved. Red economy credit balances already deposited will **not** be changed.\n\n"
                    f"Profiles found: **{len(profile_ids)}**\n"
                    f"Configured servers found: **{len(guilds)}**\n\n"
                    f"To proceed, run `{ctx.clean_prefix}fortunereset confirm`."
                ),
                color=discord.Color.red(),
            )
            embed.set_footer(text="Bot owner only • Confirmation required")
            return await ctx.send(embed=embed)

        if self._resetting or self._reset_lock.locked():
            return await ctx.send("A FortuneGarden reset is already in progress.")
        async with self._reset_lock:
            if self._resetting:
                return await ctx.send("A FortuneGarden reset is already in progress.")
            self._resetting = True
            try:
                users = await self.config.all_users()
                legacy = await self.config.all_members()
                guilds = await self.config.all_guilds()
                profile_ids = {str(user_id) for user_id in users}
                legacy_count = 0
                for guild_id, members in legacy.items():
                    for user_id in members:
                        legacy_count += 1
                        profile_ids.add(str(user_id))

                for user_id in users:
                    await self.config.user_from_id(int(user_id)).clear()

                for guild_id, members in legacy.items():
                    for user_id in members:
                        await self.config.member_from_ids(int(guild_id), int(user_id)).clear()

                for guild_id in guilds:
                    guild_conf = self.config.guild_from_id(int(guild_id))
                    await guild_conf.fortunes.set({})
                    await guild_conf.trade_offers.set({})
                    await guild_conf.community_garden.set({
                        "xp": 0,
                        "level": 1,
                        "contributions": {},
                        "milestones": [],
                    })

                await self.config.member_migration_version.set(1)
                self._migration_complete = True
                log.warning(
                    "FortuneGarden global reset completed by owner %s: %s profiles, %s legacy member records, %s guilds.",
                    ctx.author.id, len(profile_ids), legacy_count, len(guilds)
                )
            except Exception:
                log.exception("FortuneGarden global reset failed; some data may already have been cleared.")
                return await ctx.send(
                    "❌ The reset encountered an error. Some data may already have been cleared, so inspect the bot logs before retrying."
                )
            finally:
                self._resetting = False

        await ctx.send(
            "✅ **FortuneGarden has been reset globally.**\n"
            f"Cleared **{len(profile_ids)}** user profiles (including legacy records), planted seeds and pending reward schedules; "
            f"reset community gardens in **{len(guilds)}** servers; and removed pending trade offers.\n"
            "Server configuration and existing Red economy balances were preserved."
        )

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="fortuneadmin", help="Inspect or manage a member's garden. Actions: inspect, addseeds, removeseeds, addxp, addcredits.")
    async def fortuneadmin(self, ctx, member: discord.Member, action: str = "inspect", amount: int = 1):
        action = action.lower()
        lock = self._member_lock(ctx.guild.id, member.id)
        async with lock:
            member_conf = self.config.user(member)
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
