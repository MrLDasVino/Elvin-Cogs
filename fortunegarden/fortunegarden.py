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

# Banner image URLs – replace these placeholders with your actual image links
SEED_BANNER = "https://files.catbox.moe/i1787b.png"
PLANT_BANNER = "https://files.catbox.moe/7btmdw.png"
LIST_BANNER = "https://files.catbox.moe/43lzl6.png"
REWARD_BANNERS = {
    "currency": "https://files.catbox.moe/bn35ib.png",
    "prompt":   "https://files.catbox.moe/6oqu0n.png",
    "fortune":  "https://files.catbox.moe/z1gy0f.png",
    "advice":   "https://files.catbox.moe/3nr7zo.png",
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
    
MIN_CREDITS = 100
MAX_CREDITS = 300

class FortuneGarden(commands.Cog):
    """
    FortuneGarden — users earn seeds by chatting (max one per hour),
    then plant seeds that bloom into random rewards with rich embeds.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210987)
        default_guild = {
            "fortunes": {},
            "min_credits": MIN_CREDITS,
            "max_credits": MAX_CREDITS,
            "discover_message": None,  # None → fall back to DEFAULT_DISCOVER_MSG
        }
        default_member = {"seeds": 0, "last_earned": None, "opt_out": False}
        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)
        
    def cog_load(self):
        self.bloom_loop.start()

    def cog_unload(self):
        self.bloom_loop.cancel()        

    @tasks.loop(seconds=60.0)
    async def bloom_loop(self):
        """Process seeds that are due, one guild at a time."""
        now = datetime.utcnow()
        all_guilds = await self.config.all_guilds()

        for guild_id, data in all_guilds.items():
            fortunes = data["fortunes"]
            min_amt = data.get("min_credits", MIN_CREDITS)
            max_amt = data.get("max_credits", MAX_CREDITS)
            changed = False

            for fid, info in list(fortunes.items()):
                bloom_dt = datetime.fromisoformat(info["bloom_time"])
                if info.get("processed") or now < bloom_dt:
                    continue

                # —— resolve guild/channel/member with cache-then-fetch ——
                guild = self.bot.get_guild(int(guild_id))
                if not guild:
                    fortunes.pop(fid); changed = True; continue

                ch_id = info["channel_id"]
                channel = guild.get_channel(ch_id)
                if not channel:
                    try:
                        channel = await self.bot.fetch_channel(ch_id)
                    except discord.NotFound:
                        fortunes.pop(fid); changed = True; continue

                owner_id = info["owner_id"]
                member = guild.get_member(owner_id)
                if not member:
                    try:
                        member = await guild.fetch_member(owner_id)
                    except discord.NotFound:
                        fortunes.pop(fid); changed = True; continue

                # —— pick & send reward ——  
                try:
                    reward_types = ["currency", "prompt", "fortune", "advice"]
                    reward_type = random.choice(reward_types)
            
                    # build a unified, rich embed
                    embed = discord.Embed(
                        title="🌸 Your Fortune Seed Has Bloomed!",
                        color=discord.Color.random(),
                        timestamp=datetime.utcnow()
                    )
                    # show who it’s for
                    embed.set_author(
                        name=member.display_name,
                        icon_url=member.display_avatar.url
                    )
                    # big illustration background
                    embed.set_image(url=REWARD_BANNERS[reward_type])
                    # keep track of the seed
                    embed.set_footer(text=f"Seed ID: {fid}")

                    if reward_type == "currency":
                        amount = random.randint(min_amt, max_amt)
                        await bank.deposit_credits(member, amount)
    
                        #  single-string API: pass `amount` to get the correct form
                        currency_name = await bank.get_currency_name(guild)
                        embed.add_field(
                            name="💰 You received",
                            value=f"**{amount}** {currency_name}",
                            inline=False
                        )

                    elif reward_type == "prompt":
                        prompt = random.choice(PROMPTS)
                        embed.add_field(
                            name="✏️ Writing Prompt",
                            value=f"> {prompt}",
                            inline=False
                        )

                    elif reward_type == "fortune":
                        fortune = random.choice(FORTUNES)
                        embed.add_field(
                            name="🔮 Fortune",
                            value=f"> {fortune}",
                            inline=False
                        )

                    else:  
                        advice = random.choice(ADVICE)
                        embed.add_field(
                            name="💡 Advice",
                            value=f"> {advice}",
                            inline=False
                        )

                    await channel.send(content=member.mention, embed=embed)
                    fortunes[fid]["processed"] = True
                    changed = True

                except discord.HTTPException as http_exc:
                    log.warning(f"Transient issue sending seed {fid}: {http_exc}")

                except Exception as exc:
                    log.error(f"Fatal error blooming seed {fid}: {exc}", exc_info=True)
                    fortunes.pop(fid)
                    changed = True

            # —— cleanup old processed seeds ——  
            cutoff = now - timedelta(days=1)
            for fid, info in list(fortunes.items()):
                if info.get("processed") and datetime.fromisoformat(info["bloom_time"]) < cutoff:
                    fortunes.pop(fid); changed = True

            if changed:
                gid = int(guild_id)
                await self.config.guild_from_id(gid).fortunes.set(fortunes)

    @bloom_loop.before_loop
    async def before_bloom(self):
        """Delay starting the bloom_loop until after ready."""
        await self.bot.wait_until_ready()


    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        member_conf = self.config.member(message.author)
        data = await member_conf.all()

        # Respect opt-out: do not award seeds to opted-out members
        if data.get("opt_out"):
            return

        last = data["last_earned"]
        now = datetime.utcnow()

        if last and now - datetime.fromisoformat(last) < timedelta(hours=5):
            return

        if random.random() < 0.05:
            new_count = data["seeds"] + 1
            await member_conf.seeds.set(new_count)
            await member_conf.last_earned.set(now.isoformat())

            guild_conf = self.config.guild(message.guild)
            template = await guild_conf.discover_message() or DEFAULT_DISCOVER_MSG

            # compute variables
            prefix = (await self.bot.get_prefix(message))[0]
            plural = "s" if new_count != 1 else ""
            content = template.format(
                mention=message.author.mention,
                seeds=new_count,
                plural=plural,
                prefix=prefix
            )
            await message.channel.send(content)


    @commands.guild_only()
    @commands.command(
        name="fortuneseeds",                             
        help="Show how many fortune seeds you or another member has."
    )
    async def fortuneseeds(self, ctx, member: discord.Member = None):
        """
        Show how many fortune seeds a user has.
        """
        # default to command author if no member specified
        member = member or ctx.author

        seeds = await self.config.member(member).seeds()
        embed = discord.Embed(
            title="🌱 Fortune Seeds",
            description=(
                f"{member.mention} has **{seeds}** fortune seed"
                f"{'s' if seeds != 1 else ''}."
            ),
            colour=discord.Colour.random()
        )
        embed.set_image(url=SEED_BANNER)
        await ctx.send(embed=embed)

    @commands.guild_only()
    @commands.command()
    async def plantfortune(self, ctx):
        """
        Plant a fortune seed (consumes 1 seed) that will bloom in 1–12 hours.
        """
        member_conf = self.config.member(ctx.author)
        seeds = await member_conf.seeds()
        if seeds < 1:
            return await ctx.send(
                f"{ctx.author.mention}, you have no fortune seeds! Chat more to earn some."
            )

        await member_conf.seeds.set(seeds - 1)
        delay = random.randint(1, 12)
        bloom_time = datetime.utcnow() + timedelta(hours=delay)
        fid = str(int(datetime.utcnow().timestamp() * 1000))

        new_seed = {
            "owner_id": ctx.author.id,
            "channel_id": ctx.channel.id,
            "bloom_time": bloom_time.isoformat(),
            "processed": False
        }

        guild_conf = self.config.guild(ctx.guild)
        fortunes = await guild_conf.fortunes()
        fortunes[fid] = new_seed
        await guild_conf.fortunes.set(fortunes)

        embed = discord.Embed(
            title="🌱 Seed Planted",
            description=(
                f"{ctx.author.mention}, your seed will bloom in **{delay}** hour(s)."
            ),
            colour=discord.Colour.random()
        )
        embed.add_field(name="Seed ID", value=fid, inline=True)
        embed.add_field(name="Seeds Left", value=f"{seeds - 1}", inline=True)
        embed.set_image(url=PLANT_BANNER)
        await ctx.send(embed=embed)

    @commands.guild_only()
    @commands.command()
    async def listfortunes(self, ctx):
        """List your planted fortune seeds and their statuses."""
        fortunes = await self.config.guild(ctx.guild).fortunes()
        now = datetime.utcnow()
        lines = []
        for fid, info in fortunes.items():
            if info["owner_id"] != ctx.author.id:
                continue
            bloom_dt = datetime.fromisoformat(info["bloom_time"])
            if info.get("processed"):
                status = "🌸 Bloomed"
            else:
                rem = bloom_dt - now
                hrs = int(rem.total_seconds() // 3600)
                mins = int((rem.total_seconds() % 3600) // 60)
                status = f"⌛ {hrs}h {mins}m left"
            lines.append(f"ID `{fid}` — {status}")

        if not lines:
            return await ctx.send("You have no active fortune seeds.")

        embed = discord.Embed(
            title="🌱 Your Planted Seeds",
            description="\n".join(lines),
            colour=discord.Colour.random()
        )
        embed.set_image(url=LIST_BANNER)
        await ctx.send(embed=embed)

    @commands.guild_only()
    @commands.command()
    async def removefortune(self, ctx, fid: str):
        """Remove one of your unbloomed fortune seeds by ID."""
        guild_conf = self.config.guild(ctx.guild)
        fortunes = await guild_conf.fortunes()
        info = fortunes.get(fid)
        if not info:
            return await ctx.send("No fortune seed with that ID.")
        if info["owner_id"] != ctx.author.id and not ctx.author.guild_permissions.manage_guild:
            return await ctx.send("You don't have permission to remove this seed.")
        fortunes.pop(fid)
        await guild_conf.fortunes.set(fortunes)
        await ctx.send(f"🗑️ Removed fortune seed `{fid}`.")
        
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(
        name="setfortunepayout",
        help="Set the min and max credits granted when a seed blooms."
    )
    async def setfortunepayout(self, ctx, min_amt: int, max_amt: int):
        """
        Usage:  setfortunepayout <min> <max>
        Example: setfortunepayout 50 500
        """
        if min_amt < 0 or max_amt < min_amt:
            return await ctx.send("⚠️ Invalid range. Ensure 0 ≤ min ≤ max.")

        guild_conf = self.config.guild(ctx.guild)
        await guild_conf.min_credits.set(min_amt)
        await guild_conf.max_credits.set(max_amt)
        await ctx.send(f"✅ Fortune payout range updated to **{min_amt}**–**{max_amt}** credits.")
        
    @commands.is_owner()
    @commands.command(name="flushfortunes", help="Force the bloom_loop to run instantly.")
    async def flushfortunes(self, ctx):
        """Run one pass of bloom_loop right now."""
        await self.bloom_loop()
        await ctx.send("🔄 Fortune loop flushed. All past-due seeds have been processed.")
        
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(
        name="setfortunemessage",
        help=(
            "Customize the discovery message.  \n"
            "You may use these placeholders:\n"
            "`{mention}` `{seeds}` `{plural}` `{prefix}`\n"
            "Pass empty to reset to default."
        )
    )
    async def setfortunemessage(self, ctx, *, template: str = None):
        """
        Examples:
          • {mention} 🌱 You got {seeds} seed{plural}! Use {prefix}plantfortune to grow it.
          • Congrats {mention}! {seeds} now in bag. Plant with {prefix}plantfortune.
        """
        # normalize empty → None
        new_tmpl = template.strip() if template else None
 
        # validate: must include {mention} and {seeds}
        if new_tmpl and ("{mention}" not in new_tmpl or "{seeds}" not in new_tmpl):
            return await ctx.send(
                "⚠️ Your template must include **{mention}** and **{seeds}**."
            )
 
        await self.config.guild(ctx.guild).discover_message.set(new_tmpl)
        if new_tmpl:
            await ctx.send("✅ Fortune-discover message updated.")
        else:
            await ctx.send("✅ Fortune-discover message reset to default.")
        
        
    @commands.guild_only()
    @commands.command(
        name="seedopt",
        help="Manage receiving fortune seeds. Usage: seedopt off|on|status|help"
    )
    async def seedopt(self, ctx, choice: str = None):
        """
        seedopt off    -> stop receiving seeds (opt out)
        seedopt on     -> start receiving seeds again (opt in)
        seedopt status -> show current opt state
        seedopt help   -> show this help / instructions
        """
        member_conf = self.config.member(ctx.author)
        current = await member_conf.opt_out()
    
        if choice is None:
            choice = "help"
        choice = choice.lower()
    
        if choice in ("help", "h"):
            help_text = (
                "SeedOpt Help\n\n"
                "• To stop receiving seeds, run: `seedopt off`\n"
                "  This will opt you out; you will not be awarded seeds from chat.\n\n"
                "• To start receiving seeds again, run: `seedopt on`\n\n"
                "• To check your current setting, run: `seedopt status`\n\n"
                "Notes: Opt-out is stored per-member and can be changed at any time."
            )
            return await ctx.send(help_text)
    
        if choice in ("off", "false", "optout", "out"):
            if current:
                return await ctx.send("✅ You are already opted out of receiving fortune seeds.")
            await member_conf.opt_out.set(True)
            return await ctx.send("🚫 You have opted out. You will no longer receive fortune seeds. Use `seedopt on` to opt back in.")
    
        if choice in ("on", "true", "optin", "in"):
            if not current:
                return await ctx.send("✅ You are already opted in to receiving fortune seeds.")
            await member_conf.opt_out.set(False)
            return await ctx.send("✅ You have opted in. You will now receive fortune seeds again. Use `seedopt off` to opt out.")
    
        if choice == "status":
            status = "opted out" if current else "opted in"
            return await ctx.send(f"ℹ️ You are currently **{status}** of receiving fortune seeds.")
    
        return await ctx.send("⚠️ Invalid option. Use `seedopt help` for instructions.")

        
