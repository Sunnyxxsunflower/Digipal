import os
import sys
import math
import json
import plistlib
import random
import time
import threading
import subprocess
import re
from datetime import datetime, date, timedelta

from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, QRect
from PySide6.QtGui import (QFontMetrics, QPainter, QColor, QPen, QBrush, QPolygonF,
                           QFont, QGuiApplication, QTextOption, QCursor,
                           QRegion, QPixmap, QPainterPath, QRadialGradient, QTextCursor)
from PySide6.QtWidgets import (QApplication, QWidget, QMenu, QInputDialog,
                               QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
                               QListWidgetItem, QPushButton, QLabel, QLineEdit,
                               QTimeEdit, QCheckBox, QMessageBox, QGridLayout,
                               QColorDialog, QButtonGroup, QRadioButton, QFrame, QTabWidget,
                               QScrollArea, QComboBox, QSpinBox, QLayout, QStackedWidget,
                               QGraphicsView, QGraphicsScene, QSlider, QCalendarWidget,
                               QPlainTextEdit, QFileDialog)
from PySide6.QtCore import QTime, QRect, QSize, QPoint, QUrl, QDate

IS_WIN = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_MAC = sys.platform == "darwin"
HELPER = IS_WIN or IS_LINUX          # these use the digiwin / digilinux helper module
if IS_LINUX and os.environ.get("WAYLAND_DISPLAY") and os.environ.get("DISPLAY") \
        and "QT_QPA_PLATFORM" not in os.environ:
    # Wayland doesn't let apps place their own windows (she couldn't walk around), so she
    # runs through XWayland instead
    os.environ["QT_QPA_PLATFORM"] = "xcb"
if (IS_WIN and sys.stderr is None) or IS_LINUX:
    # started without a console window (pythonw / app menu): keep a log next to Digi instead
    try:
        _log = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "digipal.log"),
                    "a", encoding="utf-8", buffering=1)
        sys.stderr = sys.stdout = _log
    except Exception:
        pass

try:
    import digivoice as dv          # her ears (speech recognition)
except Exception as _ex:
    print("voice code didn't load:", _ex, file=sys.stderr)
    dv = None

try:
    if IS_WIN:
        import digiwin as W         # Windows versions of the Mac-only tricks
    elif IS_LINUX:
        import digilinux as W       # ...and the Linux versions
    else:
        W = None
except Exception as _ex:
    print("platform helper didn't load:", _ex, file=sys.stderr)
    W = None

DEFAULT_MIC = "Mac default" if IS_MAC else "System default"

# what to run again if something's missing
INSTALL_HINT = ("Run 'Install DigiPal' again~" if IS_WIN else
                "Run install_linux.sh again~" if IS_LINUX else "Run 'Install Digi's Ears'~")

try:
    from AppKit import NSWorkspace
    HAS_APPKIT = True
except Exception:
    HAS_APPKIT = False

try:
    import Quartz
    HAS_QUARTZ = True
except Exception:
    HAS_QUARTZ = False

# on Windows, keep her (and her toys) out of the taskbar
TOOL_FLAG = Qt.Tool if HELPER else Qt.Widget

# on a Mac, Qt's "bring to front" also makes the whole app active, which pulls your typing
# away from whatever you're working in. Digi only ever wants to be seen, never to grab the keyboard.
os.environ.setdefault("QT_MAC_SET_RAISE_PROCESS", "0")



def mac_keep_floating(widget):
    """Mac: keep one of Digi's windows floating above your other windows, on every desktop,
    without ever making her app active (so she never takes your typing). Qt sets this when the
    window first shows, but it can get lost later and then she ends up hidden behind a window."""
    if not (IS_MAC and HAS_APPKIT) or widget is None or not widget.isVisible():
        return
    try:
        import objc
        import AppKit
        win = objc.objc_object(c_void_p=int(widget.winId())).window()
        if win is None:
            return
        if win.level() < AppKit.NSFloatingWindowLevel:
            print("keep floating: level was %d, fixing" % win.level(), file=sys.stderr, flush=True)
            win.setLevel_(AppKit.NSFloatingWindowLevel)
            win.orderFrontRegardless()            # back on top, without activating her app
        # is some other app's window sitting on top of her right now? then pop back in front
        if HAS_QUARTZ:
            above = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionOnScreenAboveWindow
                | Quartz.kCGWindowListExcludeDesktopElements, win.windowNumber()) or []
            g = widget.frameGeometry()
            me = os.getpid()
            for info in above:
                if info.get("kCGWindowOwnerPID") == me or info.get("kCGWindowAlpha", 1) < 0.05:
                    continue
                if info.get("kCGWindowLayer", 0) > win.level():
                    continue                       # the menu bar, the Dock, pop-up menus...
                b = info.get("kCGWindowBounds") or {}
                x, y = b.get("X", 0), b.get("Y", 0)
                w, h = b.get("Width", 0), b.get("Height", 0)
                if x < g.right() and x + w > g.left() and y < g.bottom() and y + h > g.top():
                    now = time.time()
                    if now - getattr(widget, "_cover_note", 0) > 60:
                        widget._cover_note = now
                        print("keep floating: %s (layer %s) was covering her, my level %d" % (
                            info.get("kCGWindowOwnerName"), info.get("kCGWindowLayer"),
                            win.level()), file=sys.stderr, flush=True)
                    if win.level() < AppKit.NSStatusWindowLevel:
                        win.setLevel_(AppKit.NSStatusWindowLevel)   # one step higher, to be sure
                    win.orderFrontRegardless()
                    break
        if win.hidesOnDeactivate():
            win.setHidesOnDeactivate_(False)
        want = (AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
        if (win.collectionBehavior() & want) != want:
            win.setCollectionBehavior_(win.collectionBehavior() | want)
    except Exception as ex:
        print("keep floating:", ex, file=sys.stderr, flush=True)


# can she see where other windows are (to sit on them / peek around them)?
HAS_WINLIST = HAS_QUARTZ or (HELPER and W is not None)

# ---- EDIT YOUR REMINDERS HERE (24-hour time, "HH:MM") ----
# A reminder is ("time", "message") and repeats every day.
# Add a third part to limit it to certain days, like:
#   ("19:00", "D&D time!", ["Sun", "Mon"])
REMINDERS = [
    ("09:00", "Good morning! Breakfast time!"),
    ("10:30", "Water break! Sip sip!"),
    ("12:30", "Lunch time! Go eat something yummy!"),
    ("14:00", "Water break! Sip sip!"),
    ("15:00", "Stretch time! Roll those shoulders!"),
    ("17:30", "Dinner time!"),
    ("20:00", "Water break! Sip sip!"),
    ("23:00", "Time to wind down. Goodnight soon!"),
]

# ---- GREETINGS: "MM-DD": "what she says" (birthdays too! add your own) ----
GREETINGS = {
    "01-01": "Happy New Year!",
    "02-14": "Happy Valentine's Day!",
    "07-04": "Happy 4th of July!",
    "10-31": "Happy Halloween!",
    "12-24": "Merry Christmas Eve!",
    "12-25": "Merry Christmas!",
    "12-31": "Happy New Year's Eve!",
}

# ---- TIMER CHOICES (in minutes) for the Focus timer and Remind me in... ----
TIMER_CHOICES = [1, 5, 10, 15, 20, 30, 60]
POMODORO_FOCUS = 25
POMODORO_BREAK = 5

# ---- COUNTDOWNS: she mentions these now and then ("12 days until ...") ----
# Format: ("YYYY-MM-DD", "what it is"). Add your own dates!
COUNTDOWNS = [
    ("2026-12-25", "Christmas"),
    ("2027-01-01", "New Year's"),
]
DND_DAYS = []   # your D&D / game nights (set them in Customize -> Personal settings)

# ---- OTHER SETTINGS ----
SLEEP_HOURS = ("00:30", "08:30")   # she naps between these times
EYE_REST_MINUTES = 30              # eye-rest nudge every this many minutes...
EYE_REST_HOURS = (11, 19)          # ...but only between these hours (24h)
BATTERY_LOW = 20                   # she gets hungry at this battery percent

WELCOME_LINES = ["Welcome back!", "Welcome back! I missed you~", "You're back! Yay!"]
STEAM_OPEN_LINES = ["Game time?", "Ooh, Steam! Game time?"]
# the first-time tour (brand new Digis): each step is what she says + the buttons under her
INTRO_STEPS = [
    ("Hi hi! I'm Digi, your new desktop pal! \U0001F49C I'll keep you company while you work and play.",
     [("Hi Digi!", "next")]),
    ("NAME", []),
    ("You can pick me up and carry me anywhere: just drag me with your mouse! Wheee~",
     [("Next \u25B8", "next")]),
    ("Right-click me any time for my menu: timers, games, my modes, meditation and lots more!",
     [("Next \u25B8", "next")]),
    ("Want to change my hair or give me a cute hat? Shift-click me, or right-click \u2192 Customize Digi! \u2728",
     [("Show me!", "customize"), ("Next \u25B8", "next")]),
    ("I can keep your lists too: water, to-dos, reminders and birthdays. "
     "They're on the Lists tab in Customize! \U0001F4CB", [("Show me!", "lists"), ("Next \u25B8", "next")]),
    ("I can also meditate with you, watch movies or play games in the corner, "
     "and remind you to drink water~ Check out Modes in my menu!", [("Next \u25B8", "next")]),
    ("That's the tour! I'll be right here whenever you need me. Let's be friends! \U0001F49C",
     [("Yay!", "done")]),
]

# the modes row (right-click > Modes): one round button each
MODE_BUTTONS = [("\U0001F3AE\nGames", "gaming"), ("\U0001F409\nD&&D", "dnd"), ("\U0001F37F\nMovie", "movie"),
                ("\U0001F3A5\nStream", "stream"), ("\U0001F4E3\nCheer", "cheer"),
                ("\U0001F319\nNone", "off"), ("\u2715", "close")]
# rock, paper, scissors
RPS_BUTTONS = [("\u270A\nRock", "rock"), ("\u270B\nPaper", "paper"), ("\u270C\ufe0f\nScissors", "scissors"),
               ("\u2715", "close")]
RPS_EMOJI = {"rock": "\u270A", "paper": "\u270B", "scissors": "\u270C\ufe0f"}
RPS_BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}     # each one beats the next
RPS_WIN = ["I win! Hehe~", "Yay, I got you!", "Victory! \u2728", "Ha! Better luck next time~"]
RPS_LOSE = ["Aww, you got me!", "Nooo~ you win this one!", "Hmph... nice one!", "You're too good!"]
RPS_TIE = ["Same! Great minds~", "A tie! Again!", "Jinx! \U0001F440"]

# trivia: (question, right answer, wrong, wrong, wrong[, fun fact]). Answers stay short: they're buttons.
TRIVIA = {
    "anime": [
        ("Which studio made Spirited Away?", "Studio Ghibli", "Toei Animation", "Madhouse", "Kyoto Animation"),
        ("Who directed Spirited Away?", "Hayao Miyazaki", "Makoto Shinkai", "Mamoru Hosoda", "Satoshi Kon"),
        ("Who directed Your Name?", "Makoto Shinkai", "Hayao Miyazaki", "Mamoru Hosoda", "Hideaki Anno"),
        ("What is Pikachu's type?", "Electric", "Fire", "Normal", "Psychic"),
        ("What's Ash's hometown in Pokémon?", "Pallet Town", "Viridian City", "Cerulean City", "Pewter City"),
        ("In Naruto, which village is Naruto from?", "Hidden Leaf", "Hidden Sand", "Hidden Mist", "Hidden Cloud",
         "Its other name is Konoha."),
        ("In One Piece, what does Luffy want to become?", "King of the Pirates", "A Marine admiral",
         "The best swordsman", "The greatest cook"),
        ("How many Dragon Balls summon Shenron?", "7", "5", "9", "12"),
        ("Who created Sailor Moon?", "Naoko Takeuchi", "Rumiko Takahashi", "CLAMP", "Akira Toriyama"),
        ("What is Sailor Moon's real name?", "Usagi Tsukino", "Ami Mizuno", "Rei Hino", "Minako Aino"),
        ("What does Tuxedo Mask throw?", "A rose", "A playing card", "A star", "A sword"),
        ("In My Neighbor Totoro, what do the girls ride?", "The Catbus", "A dragon", "A paper plane", "A broom"),
        ("What's the name of Kiki's black cat?", "Jiji", "Luna", "Artemis", "Kero"),
        ("In Death Note, which Shinigami drops the notebook?", "Ryuk", "Rem", "Light", "L"),
        ("In Fullmetal Alchemist, Al's soul is bound to...", "A suit of armor", "A doll", "A sword", "A cat"),
        ("What's Eren's last name in Attack on Titan?", "Yeager", "Ackerman", "Arlert", "Braun"),
        ("Cardcaptor Sakura's little guardian beast is...", "Kero", "Mokona", "Luna", "Jiji",
         "His true form is Cerberus."),
        ("Which way is manga usually read in Japan?", "Right to left", "Left to right", "Bottom to top",
         "Back page first"),
        ("What is Deku's quirk in My Hero Academia?", "One For All", "All For One", "Half-Cold Half-Hot",
         "Explosion"),
        ("What's Tanjiro's sister's name in Demon Slayer?", "Nezuko", "Kanao", "Shinobu", "Mitsuri"),
        ("Which Eva unit does Shinji pilot?", "Unit-01", "Unit-00", "Unit-02", "Unit-13"),
        ("What's Spike's ship in Cowboy Bebop?", "Swordfish II", "Bebop", "Red Tail", "Hammerhead"),
        ("In Fruits Basket, a hugged Sohma turns into...", "An animal", "A ghost", "A statue",
         "A cloud of smoke"),
        ("In Inuyasha, Kagome travels through...", "An old well", "A mirror", "A closet", "A train tunnel"),
        ("In Spy x Family, Anya can...", "Read minds", "See the future", "Fly", "Talk to dogs",
         "Bond is the one who sees the future!"),
    ],
    "games": [
        ("What's the hero's name in The Legend of Zelda?", "Link", "Zelda", "Ganon", "Epona",
         "Zelda is the princess!"),
        ("What's the name of Link's horse?", "Epona", "Roach", "Agro", "Shadowfax"),
        ("Who is Mario's brother?", "Luigi", "Wario", "Toad", "Yoshi"),
        ("Which item makes Mario big?", "Super Mushroom", "Fire Flower", "Starman", "1-Up"),
        ("What's the town in Stardew Valley?", "Pelican Town", "Mineral Town", "Zuzu City", "Oakridge",
         "Zuzu City is the big city you leave behind."),
        ("Who runs the general store in Stardew Valley?", "Pierre", "Gus", "Clint", "Willy"),
        ("What's the town in Rune Factory 4?", "Selphia", "Alvarna", "Mineral Town", "Pelican Town"),
        ("Which Minecraft mob is green and explodes?", "Creeper", "Zombie", "Enderman", "Slime"),
        ("In Animal Crossing, who sells you a house?", "Tom Nook", "K.K. Slider", "Isabelle", "Blathers"),
        ("What does Sonic collect?", "Rings", "Coins", "Stars", "Gems"),
        ("How does Kirby copy powers?", "By inhaling enemies", "Eating mushrooms", "Collecting stars",
         "Touching gems"),
        ("Which Pac-Man ghost is red?", "Blinky", "Pinky", "Inky", "Clyde"),
        ("Where was Tetris created?", "The Soviet Union", "Japan", "The USA", "Finland"),
        ("Who is the hero of Final Fantasy VII?", "Cloud Strife", "Squall", "Tidus", "Zidane"),
        ("In Undertale, who is Papyrus's brother?", "Sans", "Toriel", "Asgore", "Flowey"),
        ("Which Kanto starter is Grass type?", "Bulbasaur", "Charmander", "Squirtle", "Pikachu"),
        ("Which Pokémon does a Water Stone make from Eevee?", "Vaporeon", "Jolteon", "Flareon", "Glaceon"),
        ("In Among Us, the bad guys are called...", "Impostors", "Traitors", "Werewolves", "Spies"),
        ("In Portal, the cake is a...", "Lie", "Trap", "Gift", "Myth"),
        ("Who is the hero of Halo?", "Master Chief", "Commander Shepard", "Marcus Fenix", "Doomguy"),
        ("What's the team called in Persona 5?", "Phantom Thieves", "Investigation Team", "SEES",
         "Shadow Operatives"),
        ("Hollow Knight takes place in...", "Hallownest", "Hyrule", "Lordran", "Rapture"),
        ("What does NPC stand for?", "Non-player character", "New player chat", "Next power card",
         "No pause control"),
        ("Which company makes the PlayStation?", "Sony", "Nintendo", "Microsoft", "Sega"),
        ("Who is the hero of Kingdom Hearts?", "Sora", "Riku", "Roxas", "Ventus"),
    ],
    "tabletop": [
        ("Which die do most D&D attack rolls use?", "d20", "d12", "d10", "d6"),
        ("A natural 20 on an attack is a...", "Critical hit", "Fumble", "Saving throw", "Short rest"),
        ("How many ability scores does D&D have?", "6", "5", "7", "8"),
        ("Which one is NOT a D&D ability score?", "Luck", "Wisdom", "Charisma", "Constitution"),
        ("With advantage, you...", "Roll 2, keep higher", "Roll 2, keep lower", "Add +5", "Reroll 1s"),
        ("Which D&D class can Wild Shape?", "Druid", "Ranger", "Monk", "Warlock"),
        ("Which D&D class is known for Sneak Attack?", "Rogue", "Bard", "Fighter", "Paladin"),
        ("What size is a level 1 Bardic Inspiration die?", "d6", "d4", "d8", "d10"),
        ("Who runs the game in D&D?", "Dungeon Master", "Keeper", "Warden", "Narrator"),
        ("Who runs the game in Monster of the Week?", "Keeper", "Warden", "Storyteller", "Dungeon Master"),
        ("Who runs the game in Mothership?", "Warden", "Keeper", "Overseer", "Captain"),
        ("In Mothership, what goes up when things go wrong?", "Stress", "Sanity", "Heat", "Doom"),
        ("In Call of Cthulhu, scary things cost you...", "Sanity", "Luck", "Charisma", "Stress"),
        ("How do you play Thousand Year Old Vampire?", "Solo, by journaling", "In teams of 4",
         "Only online", "With miniatures"),
        ("What's D&D's famous floating eye monster?", "Beholder", "Mind Flayer", "Gelatinous Cube", "Mimic"),
        ("Which monster pretends to be a treasure chest?", "Mimic", "Owlbear", "Beholder", "Kobold"),
        ("Which D&D dragon breathes fire?", "Red", "Blue", "Green", "White"),
        ("Which D&D dragon breathes lightning?", "Blue", "Black", "Green", "White"),
        ("How long is a long rest in D&D 5e?", "8 hours", "1 hour", "4 hours", "24 hours"),
        ("What spell level is a cantrip?", "Level 0", "Level 1", "Level 9", "Level 10"),
        ("What's the highest spell level in D&D 5e?", "9th", "7th", "10th", "12th"),
        ("How many dice are in a standard RPG set?", "7", "5", "6", "10",
         "d4, d6, d8, d10, percentile d10, d12 and d20."),
        ("Which die is shaped like a pyramid?", "d4", "d6", "d8", "d12"),
        ("Who created Dungeons & Dragons?", "Gygax & Arneson", "Tolkien & Lewis", "Lee & Kirby",
         "Lucas & Spielberg"),
        ("When was D&D first published?", "1974", "1964", "1984", "1994"),
        ("What's a TPK?", "Total party kill", "Top player kit", "Turn per knight", "Treasure pick key"),
    ],
    "books": [
        ("Who wrote Pride and Prejudice?", "Jane Austen", "Charlotte Brontë", "Emily Brontë",
         "Louisa May Alcott"),
        ("What does Bilbo find in Gollum's cave?", "A ring", "A sword", "A map", "A dragon egg"),
        ("Who wrote The Lord of the Rings?", "J.R.R. Tolkien", "C.S. Lewis", "George R.R. Martin",
         "Terry Pratchett"),
        ("How many March sisters are in Little Women?", "4", "3", "5", "6"),
        ("Who wrote Frankenstein?", "Mary Shelley", "Bram Stoker", "Edgar Allan Poe", "Percy Shelley"),
        ("Who wrote Dracula?", "Bram Stoker", "Mary Shelley", "Anne Rice", "Stephen King"),
        ("What does Alice follow into Wonderland?", "A white rabbit", "A black cat", "A blue bird",
         "A talking fox"),
        ("What flower does the Little Prince love?", "A rose", "A tulip", "A sunflower", "A lily"),
        ("How do they reach Narnia in The Lion, the Witch...?", "A wardrobe", "A painting", "A well",
         "A train"),
        ("Who is the captain in Moby-Dick?", "Ahab", "Nemo", "Hook", "Flint"),
        ("Which district is Katniss from?", "District 12", "District 1", "District 4", "District 13"),
        ("Where does Sherlock Holmes live?", "221B Baker Street", "10 Downing Street", "4 Privet Drive",
         "12 Grimmauld Place"),
        ("Where is Romeo and Juliet set?", "Verona", "Venice", "Rome", "Florence"),
        ("What color is Anne of Green Gables' hair?", "Red", "Black", "Blonde", "Brown"),
        ("Who is Percy Jackson's father?", "Poseidon", "Zeus", "Hades", "Apollo"),
        ("Which country is The Tale of Genji from?", "Japan", "China", "Korea", "India",
         "It's often called one of the world's first novels."),
        ("Who is the Monkey King in Journey to the West?", "Sun Wukong", "Zhu Bajie", "Sha Wujing", "Nezha"),
        ("What's Dorothy's dog called in The Wizard of Oz?", "Toto", "Rex", "Spot", "Benji"),
        ("Who wrote 1984?", "George Orwell", "Aldous Huxley", "Ray Bradbury", "H.G. Wells"),
        ("In Fahrenheit 451, what burns at 451°F?", "Paper", "Wood", "Glass", "Ice"),
        ("What's the name of Peter Pan's fairy?", "Tinker Bell", "Silvermist", "Navi", "Fawn"),
        ("Who wrote the book Howl's Moving Castle?", "Diana Wynne Jones", "Ursula K. Le Guin",
         "Neil Gaiman", "Hayao Miyazaki", "Studio Ghibli made the movie later."),
        ("Who wrote the book Kiki's Delivery Service?", "Eiko Kadono", "Hayao Miyazaki", "Naoko Takeuchi",
         "Banana Yoshimoto"),
        ("How many spirits visit Scrooge after Marley?", "3", "2", "4", "5"),
        ("Who wrote A Wizard of Earthsea?", "Ursula K. Le Guin", "Diana Wynne Jones", "Tamora Pierce",
         "Robin Hobb"),
    ],
    "general": [
        ("What's the biggest planet?", "Jupiter", "Saturn", "Neptune", "Earth"),
        ("Which planet is closest to the Sun?", "Mercury", "Venus", "Mars", "Earth"),
        ("Which planet is called the Red Planet?", "Mars", "Venus", "Jupiter", "Mercury"),
        ("How many legs does a spider have?", "8", "6", "10", "12"),
        ("What's the biggest ocean?", "Pacific", "Atlantic", "Indian", "Arctic"),
        ("What's the chemical symbol for gold?", "Au", "Ag", "Gd", "Go"),
        ("What's the tallest animal?", "Giraffe", "Elephant", "Ostrich", "Moose"),
        ("How many continents are there?", "7", "5", "6", "8"),
        ("What's the fastest land animal?", "Cheetah", "Lion", "Horse", "Greyhound"),
        ("What's the capital of Japan?", "Tokyo", "Kyoto", "Osaka", "Seoul"),
        ("What's the biggest hot desert?", "Sahara", "Gobi", "Kalahari", "Mojave"),
        ("Which gas do plants take in?", "Carbon dioxide", "Oxygen", "Nitrogen", "Helium"),
        ("What do bees make honey from?", "Nectar", "Pollen", "Leaves", "Sap"),
        ("How many hearts does an octopus have?", "3", "1", "2", "8"),
        ("At what °F does water freeze?", "32°F", "0°F", "100°F", "212°F"),
        ("What do pandas mostly eat?", "Bamboo", "Fish", "Berries", "Grass"),
        ("What's a baby kangaroo called?", "Joey", "Kit", "Cub", "Calf"),
        ("Which of these is a mammal?", "Dolphin", "Shark", "Octopus", "Salmon"),
        ("What's the hardest natural material?", "Diamond", "Gold", "Iron", "Quartz"),
        ("Which flower turns to follow the sun?", "Sunflower", "Rose", "Tulip", "Daisy",
         "Young sunflowers do, anyway! \U0001F33B"),
        ("How many days are in a leap year?", "366", "365", "364", "360"),
        ("Which bird can't fly?", "Penguin", "Eagle", "Parrot", "Owl"),
        ("What's the human body's biggest organ?", "Skin", "Liver", "Heart", "Brain"),
        ("How many keys does a piano have?", "88", "76", "61", "100"),
        ("How many colors are in a rainbow?", "7", "5", "6", "8"),
    ],
    "digi": [
        ("When is Digi's birthday?", "November 14", "February 14", "October 31", "December 25"),
        ("Who drew Digi?", "Sunny", "A robot", "Digi herself", "The dragon"),
        ("What does Digi sit on to meditate?", "A zafu cushion", "A beanbag", "A cloud", "Her bed"),
        ("What does Digi do when it's cold out?", "Shivers", "Dances", "Sleeps", "Sings"),
        ("What does Digi bring out when it rains?", "An umbrella", "A raincoat", "A boat", "A bucket"),
        ("Which is NOT one of Digi's hairstyles?", "Braids", "Twin tails", "Drill tails", "Shaggy"),
        ("What's on Digi's dragon book cover?", "A shield with a d20", "A crown", "A cat", "A moon"),
        ("What does Digi carry when you're a player?", "A sword", "A book", "A wand", "A lute"),
        ("Which die does Digi roll in D&D mode?", "d20", "d6", "d8", "d100"),
        ("What does Digi do when you take a screenshot?", "Grabs her camera", "Hides", "Waves",
         "Falls asleep"),
        ("Which of these is a Calm sound?", "River", "Thunder", "Fireworks", "Traffic"),
        ("What is Digi?", "A robot girl", "A cat girl", "A ghost", "An alien"),
        ("What happens when you boop Digi?", "She's surprised", "She sneezes", "She falls asleep",
         "She explodes"),
        ("Which game can you play with Digi?", "Rock, paper, scissors", "Chess", "Uno", "Mahjong"),
    ],
}
TRIVIA_CATS = [("\U0001F338\nAnime", "anime"), ("\U0001F3AE\nGames", "games"), ("\U0001F409\nTabletop", "tabletop"),
               ("\U0001F4DA\nBooks", "books"), ("\U0001F30D\nGeneral", "general"), ("\U0001F916\nDigi", "digi"),
               ("\U0001F3B2\nMix", "mix"), ("✏️\nMine", "mine"), ("✕", "close")]
TRIVIA_NAMES = {"anime": "Anime & manga", "games": "Video games", "tabletop": "Tabletop", "books": "Books",
                "general": "General", "digi": "All about Digi", "mix": "Mix", "mine": "My trivia"}
TRIVIA_ROUND = 10
TRIVIA_RIGHT = ["Correct! ✨", "Yes!! You got it!", "Right! So smart~", "Ding ding ding! \U0001F514"]
TRIVIA_WRONG = ["Not quite!", "Ooh, so close!", "Nope~", "Aww, not this time!"]

GAMING_START = ["Game time! \U0001F3AE I'll play over here~", "Ooh, let's play together! \U0001F3AE",
                "Player 2 ready! \U0001F3AE"]
GAMING_END = ["GG! That was fun! \U0001F3AE", "I almost beat that level!", "Good game~ \u2665"]
GAMING_LINES = ["Ooh, I found a secret!", "Level up! \u2728", "Nooo, I fell in the lava!",
                "Boss fight! \U0001F4AA", "One more round!", "I got a new high score!"]

DND_MODE_START = ["Adventure time! I'll play D&D over here~ \U0001F409",
                  "Solo campaign, here I come! \U0001F4D6", "I'll be in my corner, rolling dice~ \U0001F3B2"]
DND_MODE_END = ["Campaign saved! That was fun~ \U0001F409", "The dragon lives to fight another day!",
                "Good session! \u2665"]
DND_MODE_LINES = ["I open the treasure chest... \U0001F440", "The goblins are sneaking up! Roll to dodge~",
                  "I sneak past the sleeping dragon... shhh~", "I check the door for traps!",
                  "The innkeeper looks suspicious...", "I search the dusty library!",
                  "Time for a short rest~", "A wild owlbear appears!"]

STEAM_CHEERS = ["Yay!", "This is so fun!", "Have fun!", "Ooh, good game!"]

# ---- EDIT APP REACTIONS HERE ("App name": "what she says") ----
# The name must match the app's name exactly as it appears in the menu bar.
APP_REACTIONS = {
    "Safari": "Browsing~ find anything fun?",
    "Google Chrome": "Browsing~ find anything fun?",
    "Firefox": "Browsing~ find anything fun?",
    "Discord": "Say hi to everyone for me!",
    "DaVinci Resolve": "Editing time! You've got this!",
    "CapCut": "Editing time! You've got this!",
    "Notes": "Writing time! Let's go!",
    "Pages": "Writing time! Let's go!",
    "Microsoft Word": "Writing time! Let's go!",
    "Spotify": "Ooh, music!",
    "Music": "Ooh, music!",
    "Steam": "Game time?",
    "Terminal": "Hey, that's my house!",
}

DAY_NUMBERS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3,
               "Fri": 4, "Sat": 5, "Sun": 6}

POKE_LINES = ["Hehe!", "That tickles!", "Hi hi!", "You're doing great!", "Water break?", "Yay!"]
SLEEPY_POKE_LINES = ["Mmm... five more minutes~", "Zzz... huh?", "Mm? Oh, hi~"]
IDLE_LINES = ["...", "Keep going!", "I'm here!", "Snack time?", "Stretch your shoulders!"]
SING_LINES = ["la la la~", "lalala~", "la la~ la la~", "~la la la~", "lala~"]

ACC_MODES = ["auto", "santa", "witch", "party", "heart", "ears", "flower", "scarf",
             "sunhat", "beret", "bunny", "glasses", "bow", "star", "book", "sword", "none"]
ACC_NAMES = {"auto": "Outfit: seasonal", "santa": "Santa hat!", "witch": "Witch hat! \U0001F383",
             "party": "Party hat! \U0001F389", "heart": "Heart clip! \u2665",
             "ears": "Cat ears! Nya~", "flower": "A little flower!", "scarf": "Cozy scarf!",
             "sunhat": "Sun hat! \u2600", "beret": "A cozy beret~ \U0001F342", "bunny": "Bunny ears! Hop hop~",
             "glasses": "Ooh, smart glasses!", "bow": "A big bow! \U0001F380", "star": "A little star! \u2B50",
             "book": "My dragon book! \U0001F409", "sword": "En garde! \u2694\ufe0f",
             "none": "No outfit"}
# drawn outfits are pinned to her head in every picture; these are the poses where a flat
# drawing can sit right at all (not lying down asleep, not peeking around a window)
ACC_DROP_OK = {"idle", "blink", "happy", "walk", "sing", "surprised", "sitfloor", "typing", "cuddle_teddy",
               "cuddle_ball", "meditate", "sit", "shy", "scared", "shiver", "camera", "gaming"}
ACC_MENU = [("auto", "Seasonal (changes by month)"), ("santa", "Santa hat"),
            ("witch", "Witch hat"), ("party", "Party hat"), ("heart", "Heart clip"),
            ("ears", "Cat ears"), ("flower", "Flower"),
            ("scarf", "Scarf"), ("sunhat", "Sun hat"), ("beret", "Beret"), ("bunny", "Bunny ears"),
            ("glasses", "Glasses"), ("bow", "Big bow"), ("star", "Star clip"),
            ("book", "Dragon book"), ("sword", "Sword"), ("none", "Nothing")]
# things she holds in her hand instead of wearing on her head: hidden while her hands are busy
HAND_ACCS = ("book", "sword")
HAND_BUSY = ("typing", "camera", "gaming", "cuddle_", "meditate", "stretch", "shy", "shiver",
             "scared", "umbrella", "peek", "sleep_")

SPEED = 2.0
PAUSE_CHANCE = 0.004

BODY = QColor("#ffd6e0")
OUTLINE = QColor("#e8a0b4")
DARK = QColor("#4a3b47")
BLUSH = QColor("#ffa6bd")
HEART = QColor("#ff6b8b")
NOTE = QColor("#9b8cd9")

# ---- updates (from Digi's home on GitHub) ----
APP_VERSION = 41                       # bump this (and version.json) when you publish a new Digi
UPDATE_REPO = "Sunnyxxsunflower/Digipal"
UPDATE_RAW = "https://raw.githubusercontent.com/%s/main/" % UPDATE_REPO
APP_LOCK = None                       # the "only one Digi" lock (let go of it when restarting)

# ---- files ----
TODO_FILE = os.path.expanduser("~/.desk_pet_todo.json")
REMINDER_FILE = os.path.expanduser("~/.desk_pet_reminders.json")
WATER_FILE = os.path.expanduser("~/.desk_pet_water.json")
# the cycle tracker (off unless you turn it on). Only ever kept in this file on your computer.
CYCLE_FILE = os.path.expanduser("~/.desk_pet_cycle.json")
CYCLE_HEADSUP = ["Heads up~ your cycle might start in about 2 days \U0001F338 Maybe pack your supplies!",
                 "Psst, your cycle might be coming in a couple of days \U0001F338"]
CYCLE_TODAY = ["Your cycle might start around today \U0001F338 Be gentle with yourself!",
               "Cycle might be starting today~ \U0001F338 Tell me when it does!"]
CYCLE_CARE = ["Cozy day? Remember water and a little rest \U0001F49C",
              "Be extra kind to yourself today \U0001F338", "Warm drink and a snack? You deserve it \U0001F49C"]
WATER_GOAL = 8          # glasses per day (you can change it from her menu)
DICE = [20, 4, 6, 8, 10, 12, 100]
SIT_OFFSET = 187        # how far above the window edge she sits
KICK_LINES = ["Got it!", "Kick!", "Hehe!", "Again!", "Mine!", "Boing!"]
DRINK_LINES = ["Glug glug!", "Hydrated!", "Good job!", "Sip sip~", "Yay, water!"]
DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# ---- D&D ----
# each game: {"title", "role": "dm"/"player", "char": what she calls you at the table,
#             "days": ["Fri", ...], "start": "19:00", "hours": 4, "notes": "..."}
DND_HEADS_UP = 30                # minutes before a game she gives you a heads-up
DND_START_LINES = ["It's {title} time, {name}! Grab your dice~ \U0001F3B2",
                   "Game time, {name}! May your rolls be high \u2728",
                   "Adventure awaits, {name}! \U0001F409"]
DND_DM_LINES = ["Your players await, {name}! \U0001F4D6", "Time to run the game, {name}! You've got this~",
                "The world is yours to tell, {name}! \U0001F409"]
DND_END_LINES = ["Great session, {name}! Anything to jot in your notes? \U0001F4DC",
                 "That was fun! Rest up, {name}~", "What an adventure! Same time next week? \U0001F3B2"]


def clean_trivia(t):
    """One of your own trivia questions, checked over (or None if it's not usable)."""
    if not isinstance(t, dict):
        return None
    q = str(t.get("q", "")).strip()[:90]
    a = str(t.get("a", "")).strip()[:24]
    wrong = []
    for w in t.get("wrong") or []:
        w = str(w).strip()[:24]
        if w and w.lower() != a.lower() and w.lower() not in (x.lower() for x in wrong):
            wrong.append(w)
    if not q or not a or not wrong:
        return None
    return {"q": q, "a": a, "wrong": wrong[:3]}


def clean_dnd_game(g):
    """A saved game, checked over (or None if it's not usable)."""
    if not isinstance(g, dict):
        return None
    start = str(g.get("start", "19:00"))
    if not re.fullmatch(r"\d\d:\d\d", start) or int(start[:2]) > 23 or int(start[3:]) > 59:
        start = "19:00"
    try:
        hours = max(0.5, min(12.0, float(g.get("hours", 4))))
    except (TypeError, ValueError):
        hours = 4.0
    return {"title": str(g.get("title", "")).strip()[:40] or "Game night",
            "role": "dm" if g.get("role") == "dm" else "player",
            "char": str(g.get("char", "")).strip()[:24],
            "days": [d for d in DAY_ORDER if d in (g.get("days") or [])],
            "start": start, "hours": hours,
            "notes": str(g.get("notes", ""))[:20000]}


def dnd_starts(game, around):
    """When this game starts on the days near `around` (yesterday through a week ahead)."""
    h, m = int(game["start"][:2]), int(game["start"][3:])
    out = []
    for off in range(-1, 8):
        d = around.date() + timedelta(days=off)
        if DAY_ORDER[d.weekday()] in game["days"]:
            out.append(datetime(d.year, d.month, d.day, h, m))
    return out


def dnd_session_at(games, now):
    """(game, start, end) of the game going on right now, or None."""
    for g in games:
        for st in dnd_starts(g, now):
            end = st + timedelta(hours=g["hours"])
            if st <= now < end:
                return g, st, end
    return None


def dnd_next_game(games, now):
    """(game, start) of the next game that hasn't started yet, or None."""
    best = None
    for g in games:
        for st in dnd_starts(g, now):
            if st > now and (best is None or st < best[1]):
                best = (g, st)
    return best


def dnd_notes_text(games):
    """Notes for these games as plain text (for saving to a file)."""
    parts = []
    for g in games:
        t = datetime.strptime(g["start"], "%H:%M").strftime("%I:%M %p").lstrip("0")
        role = "GM" if g["role"] == "dm" else "Player"
        head = [g["title"], "=" * max(3, len(g["title"])),
                f"{role}" + (f" as {g['char']}" if g["char"] else ""),
                f"Game days: {', '.join(g['days']) or '(none)'} at {t}", ""]
        parts.append("\n".join(head) + "\n" + (g["notes"].strip() or "(no notes yet)") + "\n")
    stamp = datetime.now().strftime("%B %d, %Y").replace(" 0", " ")
    return f"Game night notes from Digi \u00b7 saved {stamp}\n\n" + "\n\n".join(parts)


def gm_title(g):
    """What she calls the person running the game: Dungeon Master for D&D, else Game Master."""
    t = g["title"].lower()
    dnd = "d&d" in t or "dnd" in t or "dungeon" in t
    return "Dungeon Master" if dnd else "Game Master"


def dnd_game_label(g):
    days = ", ".join(g["days"]) or "no days yet"
    t = datetime.strptime(g["start"], "%H:%M").strftime("%I:%M %p").lstrip("0")
    role = "GM \U0001F4D6" if g["role"] == "dm" else "Player \u2694\ufe0f"
    who = f" as {g['char']}" if g["char"] else ""
    return f"{g['title']}: {days} at {t} \u00b7 {role}{who}"

# ---- MEDITATION ----
MED_CHOICES = (5, 10, 15, 20, 30)        # minutes
MED_SOUNDS = [("none", "None"), ("white", "White noise"), ("pink", "Pink noise"),
              ("forest", "Forest"), ("river", "River"), ("waves", "Waves")]
MED_CHIMES = [("bell", "Soft bell"), ("bowl", "Singing bowl"), ("shurong", "Shurong bell"),
              ("windchimes", "Wind chimes"),
              ("gong", "Gong"), ("tingsha", "Tingsha"), ("none", "None")]
MED_LATER = 30                           # "Later": she asks again in this many minutes
MED_ANSWER_WAIT = 180                    # no answer this long: she quietly treats it as "Later"
BREATH = (("Breathe in...", 4), ("Hold...", 4), ("Breathe out...", 6))   # seconds per step
MED_START_LINES = ["Let's breathe together~ \U0001F33F", "Okay... nice and slow~",
                   "Getting comfy on my cushion~"]
MED_END_LINES = ["That was lovely. Feeling a little calmer? \U0001F338",
                 "Mmm... all done. Thank you for breathing with me~",
                 "Nice and calm \u2665 You did great.",
                 "Welcome back~ I hope your mind feels a little lighter."]

# ---- BIRTHDAYS ----
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
DIGI_BIRTHDAY = (11, 14)        # the day Digi was made (2026)
DIGI_BORN_YEAR = 2026
BDAY_HEADS_UP = (7, 1)          # she mentions a birthday this many days ahead (plus on the day)
BDAY_TIME = 9                   # birthday reminders come after this hour


def easter(year):
    """Easter Sunday (Gregorian calendar)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def next_birthday(month, day, today):
    """The next date (today or later) this birthday falls on. Feb 29 -> Feb 28 in other years."""
    for y in (today.year, today.year + 1):
        try:
            d = date(y, month, day)
        except ValueError:
            d = date(y, month, 28)
        if d >= today:
            return d
    return today


def days_until_birthday(month, day, today=None):
    today = today or date.today()
    return (next_birthday(month, day, today) - today).days


def birthday_label(b):
    return f"{b['name']} - {MONTHS[b['month'] - 1]} {b['day']}"


def clean_birthday(b):
    """A birthday dict from settings, or None if it's broken."""
    try:
        m, d = int(b["month"]), int(b["day"])
        if not (1 <= m <= 12 and 1 <= d <= 31):
            return None
        out = {"month": m, "day": d}
        if "name" in b:
            out["name"] = str(b["name"]).strip()[:40] or "Someone"
        return out
    except Exception:
        return None


# Optional file next to Digi's code with someone's own starting setup (name, city, schedule).
# It isn't part of the shared Digi, so everyone else starts with the plain defaults.
PERSONAL = {}
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "personal_defaults.json"),
              encoding="utf-8") as _f:
        PERSONAL = json.load(_f)
except Exception:
    PERSONAL = {}


def load_reminders():
    """Your saved reminders, or the starter list above the first time."""
    try:
        with open(REMINDER_FILE, "r") as f:
            data = json.load(f)
        out = []
        for r in data:
            days = r.get("days") or None
            out.append((r["time"], r["text"], days) if days else (r["time"], r["text"]))
        return out
    except Exception:
        start = PERSONAL.get("reminders")
        if start:
            return [(r["time"], r["text"], r["days"]) if r.get("days") else (r["time"], r["text"])
                    for r in start]
        return list(REMINDERS)


def save_reminders(items):
    data = [{"time": r[0], "text": r[1], "days": (r[2] if len(r) > 2 else None)}
            for r in items]
    with open(REMINDER_FILE, "w") as f:
        json.dump(data, f, indent=2)


def reminder_label(r):
    days = r[2] if len(r) > 2 and r[2] else None
    h, m = (int(x) for x in r[0].split(":"))
    ampm = "am" if h < 12 else "pm"
    nice = f"{(h % 12) or 12}:{m:02d}{ampm}"
    when = ", ".join(days) if days and len(days) < 7 else "every day"
    return f"{nice}  ·  {r[1]}  ({when})"


class Ball(QWidget):
    """A bouncy ball you can toss around. She chases it!"""
    SIZE = 44

    def __init__(self, area, x, y):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | TOOL_FLAG
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)    # never steal your typing
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(self.SIZE, self.SIZE)
        self.area = area
        self.x_, self.y_ = float(x), float(y)
        self.vx, self.vy = random.choice([-1, 1]) * random.uniform(6, 10), -12.0
        self.spin = 0.0
        self.held = False
        self.trail = []
        self.move(int(self.x_), int(self.y_))
        self.show()

    def cx(self):
        return self.x_ + self.SIZE / 2

    def on_floor(self):
        return self.y_ >= self.area.bottom() - self.SIZE - 1

    def step(self):
        if self.held:
            return
        a = self.area
        self.vy += 0.8
        self.x_ += self.vx
        self.y_ += self.vy
        if self.x_ < a.left():
            self.x_, self.vx = float(a.left()), abs(self.vx) * 0.8
        if self.x_ > a.right() - self.SIZE:
            self.x_, self.vx = float(a.right() - self.SIZE), -abs(self.vx) * 0.8
        if self.y_ < a.top():
            self.y_, self.vy = float(a.top()), abs(self.vy) * 0.5
        floor = a.bottom() - self.SIZE
        if self.y_ > floor:
            self.y_ = float(floor)
            self.vy = -abs(self.vy) * 0.6 if abs(self.vy) > 2.5 else 0.0
            self.vx *= 0.96
            if abs(self.vx) < 0.15:
                self.vx = 0.0
        self.spin += self.vx * 4
        self.move(int(self.x_), int(self.y_))
        self.update()

    def kick(self, direction):
        self.vx = direction * random.uniform(8, 14)
        self.vy = -random.uniform(10, 16)

    def mousePressEvent(self, e):
        self.held = True
        self.trail = [e.globalPosition().toPoint()]
        self.grab_off = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self.held:
            p = e.globalPosition().toPoint()
            self.trail = (self.trail + [p])[-4:]
            pos = p - self.grab_off
            self.x_, self.y_ = float(pos.x()), float(pos.y())
            self.move(pos)

    def mouseReleaseEvent(self, e):
        self.held = False
        if len(self.trail) >= 2:   # throw it with your mouse speed
            d = self.trail[-1] - self.trail[0]
            n = len(self.trail) - 1
            self.vx = max(-30, min(30, d.x() / n * 1.2))
            self.vy = max(-30, min(30, d.y() / n * 1.2))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(3, 3, self.SIZE - 6, self.SIZE - 6)
        p.translate(self.SIZE / 2, self.SIZE / 2)
        p.rotate(self.spin)
        p.translate(-self.SIZE / 2, -self.SIZE / 2)
        p.setPen(QPen(QColor("#1b1b1b"), 2.5))
        p.setBrush(QBrush(QColor("#ff8fb8")))
        p.drawEllipse(r)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#ffe27a")))
        p.drawPie(r, 0, 90 * 16)
        p.drawPie(r, 180 * 16, 90 * 16)
        p.setPen(QPen(QColor("#1b1b1b"), 2.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(r)
        p.end()


class Die(QWidget):
    """One die she throws. It tumbles, bounces, and lands on a number."""
    SIZE = 46

    def __init__(self, area, x, y, vx, vy, floor, sides, result):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | TOOL_FLAG
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)    # never steal your typing
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.resize(self.SIZE, self.SIZE)
        self.area, self.floor = area, floor
        self.x_, self.y_, self.vx, self.vy = float(x), float(y), vx, vy
        self.sides, self.result = sides, result
        self.shown = random.randint(1, sides)
        self.angle = random.uniform(0, 360)
        self.spin = random.uniform(14, 24) * (1 if vx > 0 else -1)
        self.settled = False
        self.age = 0
        self.move(int(self.x_), int(self.y_))
        self.show()

    def step(self):
        self.age += 1
        if self.settled:
            return
        a = self.area
        self.vy += 0.9
        self.x_ += self.vx
        self.y_ += self.vy
        if self.x_ < a.left():
            self.x_, self.vx = float(a.left()), abs(self.vx) * 0.7
        if self.x_ > a.right() - self.SIZE:
            self.x_, self.vx = float(a.right() - self.SIZE), -abs(self.vx) * 0.7
        if self.y_ > self.floor:
            self.y_ = float(self.floor)
            self.vy = -abs(self.vy) * 0.45 if abs(self.vy) > 3 else 0.0
            self.vx *= 0.8
            self.spin *= 0.7
        self.angle += self.spin
        if self.age % 3 == 0:
            self.shown = random.randint(1, self.sides)
        if self.y_ >= self.floor and self.vy == 0 and abs(self.vx) < 0.6:
            self.settled = True
            self.shown = self.result
            self.angle = 0
        self.move(int(self.x_), int(self.y_))
        self.update()

    def shape(self, c, r):
        n = {4: 3, 6: 4, 8: 4, 10: 5, 12: 5, 20: 6}.get(self.sides, 6)
        start = -90 if n != 4 or self.sides == 8 else -45
        if self.sides == 6:
            start = -45
        return QPolygonF([QPointF(c + r * math.cos(math.radians(start + i * 360 / n)),
                                  c + r * math.sin(math.radians(start + i * 360 / n)))
                          for i in range(n)])

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.SIZE / 2
        p.translate(c, c)
        p.rotate(self.angle)
        p.translate(-c, -c)
        gold = self.settled and self.sides == 20 and self.result == 20
        red = self.settled and self.sides == 20 and self.result == 1
        fill = QColor("#ffd54f") if gold else QColor("#ff8a8a") if red else QColor("#a99be0")
        p.setPen(QPen(QColor("#1b1b1b"), 2.5))
        p.setBrush(QBrush(fill))
        poly = self.shape(c, c - 3)
        p.drawPolygon(poly)
        if self.sides == 20:   # little facet lines
            p.setPen(QPen(QColor(30, 30, 30, 90), 1.2))
            tri = self.shape(c, c * 0.55)
            p.drawPolygon(QPolygonF([tri[0], tri[2], tri[4]]))
        p.setPen(QPen(QColor("#1b1b1b")))
        size = 13 if self.shown < 100 else 10
        p.setFont(QFont("Helvetica", size, QFont.Bold))
        p.drawText(QRectF(0, 0, self.SIZE, self.SIZE), str(self.shown),
                   QTextOption(Qt.AlignCenter))
        p.end()


def parse_roll(text):
    """'5d20+3' -> (5, 20, 3). Returns None if it doesn't make sense."""
    m = re.match(r"^\s*(\d*)\s*d\s*(\d+)\s*(?:([+-])\s*(\d+))?\s*$", text.lower())
    if not m:
        return None
    count = int(m.group(1) or 1)
    sides = int(m.group(2))
    mod = int(m.group(4) or 0) * (-1 if m.group(3) == "-" else 1)
    if not (1 <= count <= 50 and 2 <= sides <= 1000):
        return None
    return count, sides, mod


# ---- tarot: the 22 Major Arcana (name, symbol, upright meaning, reversed meaning) ----
TAROT = [
    ("0", "The Fool", "\U0001F392", "new beginnings & a leap of faith", "hold off on that leap for a sec"),
    ("I", "The Magician", "\u2728", "you have everything you need", "untapped talent, focus up"),
    ("II", "The High Priestess", "\U0001F319", "trust your intuition", "listen to your inner voice"),
    ("III", "The Empress", "\U0001F33A", "creativity & abundance", "take care of yourself first"),
    ("IV", "The Emperor", "\U0001F451", "structure & steady progress", "loosen the reins a little"),
    ("V", "The Hierophant", "\U0001F4DC", "learning from tradition", "make your own rules"),
    ("VI", "The Lovers", "\U0001F495", "harmony & heartfelt choices", "check in with your values"),
    ("VII", "The Chariot", "\U0001F3C7", "willpower & momentum", "regain your direction"),
    ("VIII", "Strength", "\U0001F981", "quiet courage", "be gentle with yourself"),
    ("IX", "The Hermit", "\U0001F56F\ufe0f", "rest & reflection", "time to reconnect with people"),
    ("X", "Wheel of Fortune", "\U0001F3A1", "luck is turning your way", "ride out the bumpy bit"),
    ("XI", "Justice", "\u2696\ufe0f", "fairness & clear decisions", "double-check the details"),
    ("XII", "The Hanged Man", "\U0001F643", "a new perspective", "stop stalling, you've got this"),
    ("XIII", "Death", "\U0001F98B", "an ending that makes room for something new", "let go of what's done"),
    ("XIV", "Temperance", "\U0001F375", "balance & patience", "find your balance again"),
    ("XV", "The Devil", "\u26d3\ufe0f", "notice what's holding you back", "breaking free!"),
    ("XVI", "The Tower", "\u26a1", "a sudden shake-up", "dodged a lightning bolt"),
    ("XVII", "The Star", "\u2b50", "hope, healing & a fresh start", "keep the faith"),
    ("XVIII", "The Moon", "\U0001F315", "dreams & mystery", "the fog is clearing"),
    ("XIX", "The Sun", "\u2600\ufe0f", "joy & success!", "the sun's still there behind the clouds"),
    ("XX", "Judgement", "\U0001F4EF", "a wake-up call & fresh start", "don't be so hard on yourself"),
    ("XXI", "The World", "\U0001F30D", "completion & celebration", "almost there, finish strong"),
]

SNACKS = [("\U0001F36A", "cookie"), ("\U0001F369", "donut"), ("\U0001F359", "onigiri"),
          ("\U0001F361", "dango"), ("\U0001F9C1", "cupcake"), ("\U0001F353", "strawberry"),
          ("\U0001F36B", "chocolate"), ("\U0001F370", "cake"), ("\U0001F95F", "dumpling"),
          ("\U0001F36E", "pudding"), ("\U0001F9CB", "boba"), ("\U0001F95E", "pancakes")]


class TarotCard(QWidget):
    """A card she pulls out. It flips over; click it to hear what it means."""
    W, H = 92, 144

    def __init__(self, x, y, card, reversed_, on_click):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | TOOL_FLAG
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)    # never steal your typing
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(self.W, self.H)
        self.card, self.rev, self.on_click = card, reversed_, on_click
        self.flip = 0            # 0..20: card back -> face
        self.move(int(x), int(y))
        self.show()

    def step(self):
        if self.flip < 20:
            self.flip += 1
            self.update()

    def mousePressEvent(self, e):
        self.on_click()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        k = self.flip / 20.0
        sx = abs(math.cos(math.pi * k))          # squeeze to 0 halfway, then open
        face = k >= 0.5
        p.translate(self.W / 2, self.H / 2)
        p.scale(max(sx, 0.02), 1)
        if face and self.rev:
            p.rotate(180)
        p.translate(-self.W / 2, -self.H / 2)
        r = QRectF(3, 3, self.W - 6, self.H - 6)
        p.setPen(QPen(QColor("#1b1b1b"), 2.5))
        if not face:
            p.setBrush(QBrush(QColor("#4b3f7a")))
            p.drawRoundedRect(r, 9, 9)
            p.setPen(QPen(QColor("#f2c85b"), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(7, 7, -7, -7), 6, 6)
            p.setFont(QFont("Helvetica", 26))
            p.drawText(r, "\u2726", QTextOption(Qt.AlignCenter))
        else:
            num, name, sym = self.card[0], self.card[1], self.card[2]
            p.setBrush(QBrush(QColor("#fbf6ea")))
            p.drawRoundedRect(r, 9, 9)
            p.setPen(QPen(QColor("#c9a43c"), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(6, 6, -6, -6), 6, 6)
            p.setPen(QPen(QColor("#4b3f7a")))
            p.setFont(QFont("Helvetica", 10, QFont.Bold))
            p.drawText(QRectF(0, 12, self.W, 16), num, QTextOption(Qt.AlignCenter))
            p.setFont(QFont("Helvetica", 34))
            p.drawText(QRectF(0, 34, self.W, 56), sym, QTextOption(Qt.AlignCenter))
            opt = QTextOption(Qt.AlignCenter)
            opt.setWrapMode(QTextOption.WordWrap)
            p.setFont(QFont("Helvetica", 9, QFont.Bold))
            p.drawText(QRectF(8, 96, self.W - 16, 34), name.upper(), opt)
        p.end()


class Snack(QWidget):
    """A snack she offers you. Click it to take a bite!"""
    SIZE = 74

    def __init__(self, x, y, emoji, on_bite):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | TOOL_FLAG
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)    # never steal your typing
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(self.SIZE, self.SIZE)
        self.emoji, self.on_bite = emoji, on_bite
        self.bites = []
        self.crumbs = []
        self.pop = 0
        self.move(int(x), int(y))
        self.show()

    def step(self):
        if self.pop < 10:
            self.pop += 1
        for c in self.crumbs:
            c[0] += c[2]
            c[1] += c[3]
            c[3] += 0.6
        self.crumbs = [c for c in self.crumbs if c[1] < self.SIZE]
        self.update()

    def mousePressEvent(self, e):
        # a bite out of the edge nearest where you clicked
        cx = cy = self.SIZE / 2
        dx, dy = e.position().x() - cx, e.position().y() - cy
        d = math.hypot(dx, dy) or 1
        self.bites.append((cx + dx / d * 24, cy + dy / d * 24))
        for _ in range(5):
            self.crumbs.append([cx + dx / d * 20, cy + dy / d * 20,
                                random.uniform(-2, 2), random.uniform(-3, 0)])
        self.on_bite(len(self.bites))

    def paintEvent(self, event):
        img = QPixmap(self.SIZE, self.SIZE)
        img.fill(Qt.transparent)
        q = QPainter(img)
        q.setRenderHint(QPainter.Antialiasing)
        scale = min(1.0, 0.3 + self.pop / 10 * 0.7)
        q.setFont(QFont("Apple Color Emoji", int(40 * scale)))
        q.drawText(QRectF(0, 0, self.SIZE, self.SIZE), self.emoji, QTextOption(Qt.AlignCenter))
        q.setCompositionMode(QPainter.CompositionMode_Clear)
        q.setPen(Qt.NoPen)
        q.setBrush(QBrush(Qt.black))
        for bx, by in self.bites:            # little scalloped bite marks
            for ox in (-7, 0, 7):
                q.drawEllipse(QPointF(bx + ox, by), 9, 9)
        q.end()
        p = QPainter(self)
        p.drawPixmap(0, 0, img)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#c98b4f")))
        for c in self.crumbs:
            p.drawEllipse(QPointF(c[0], c[1]), 2, 2)
        p.end()


class Bomb(QWidget):
    """A cartoon bomb: she tosses it, the fuse fizzles, then KABOOM (harmless!)."""
    SIZE = 48
    BOOM = 240

    def __init__(self, area, x, y, vx, vy, floor):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | TOOL_FLAG
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)    # never steal your typing
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.resize(self.SIZE, self.SIZE)
        self.area, self.floor = area, floor
        self.x_, self.y_, self.vx, self.vy = float(x), float(y), vx, vy
        self.spin = 0.0
        self.fuse = 0           # ticks since it landed
        self.boom = 0           # explosion ticks
        self.done = False
        self.just_exploded = False
        self.move(int(self.x_), int(self.y_))
        self.show()

    def step(self):
        if self.boom:
            self.boom += 1
            if self.boom > 34:
                self.done = True
            self.update()
            return
        a = self.area
        landed = False
        self.vy += 0.9
        self.x_ += self.vx
        self.y_ += self.vy
        if self.x_ < a.left():
            self.x_, self.vx = float(a.left()), abs(self.vx) * 0.6
        if self.x_ > a.right() - self.SIZE:
            self.x_, self.vx = float(a.right() - self.SIZE), -abs(self.vx) * 0.6
        if self.y_ >= self.floor:
            self.y_ = float(self.floor)
            self.vy = -abs(self.vy) * 0.35 if abs(self.vy) > 4 else 0.0
            self.vx *= 0.75
            landed = self.vy == 0
        self.spin += self.vx * 5
        if landed:
            self.fuse += 1
            if self.fuse > 32:
                self.explode()
                return
        self.move(int(self.x_), int(self.y_))
        self.update()

    def explode(self):
        self.boom = 1
        self.just_exploded = True
        cx, cy = self.x_ + self.SIZE / 2, self.y_ + self.SIZE / 2
        self.resize(self.BOOM, self.BOOM)
        self.move(int(cx - self.BOOM / 2), int(cy - self.BOOM / 2))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = QColor("#1b1b1b")
        if self.boom:
            k = self.boom / 34.0
            c = self.BOOM / 2
            if self.boom < 20:                       # the flash
                r = 30 + 85 * min(1.0, self.boom / 8)
                for rad, col in ((r, "#ff7a1a"), (r * 0.72, "#ffd23f"), (r * 0.4, "#fff6c9")):
                    pts = []
                    for i in range(24):
                        a = math.radians(i * 15 + self.boom * 3)
                        rr = rad * (1.0 if i % 2 == 0 else 0.62)
                        pts.append(QPointF(c + rr * math.cos(a), c + rr * math.sin(a)))
                    p.setPen(QPen(dark, 3) if col == "#ff7a1a" else Qt.NoPen)
                    p.setBrush(QBrush(QColor(col)))
                    p.drawPolygon(QPolygonF(pts))
                if self.boom < 16:
                    p.setPen(QPen(dark, 2))
                    p.setFont(QFont("Helvetica", 22, QFont.Black))
                    p.drawText(QRectF(0, c - 20, self.BOOM, 40), "BOOM!", QTextOption(Qt.AlignCenter))
            # smoke puffs drifting out and fading
            alpha = int(200 * max(0.0, 1 - k))
            p.setPen(Qt.NoPen)
            for i in range(8):
                a = math.radians(i * 45 + 20)
                d = 40 + 70 * k
                p.setBrush(QBrush(QColor(120, 120, 130, alpha)))
                p.drawEllipse(QPointF(c + d * math.cos(a), c + d * math.sin(a) - 20 * k),
                              14 + 10 * k, 12 + 8 * k)
            p.end()
            return
        s = self.SIZE
        p.translate(s / 2, s / 2)
        p.rotate(self.spin)
        p.translate(-s / 2, -s / 2)
        p.setPen(QPen(dark, 2.5))
        p.setBrush(QBrush(QColor("#2a2a35")))
        p.drawEllipse(QRectF(5, 11, s - 12, s - 12))
        p.setBrush(QBrush(QColor("#6d6d80")))
        p.drawRect(QRectF(s / 2 - 6, 5, 12, 9))           # the cap
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(255, 255, 255, 120)))
        p.drawEllipse(QRectF(13, 18, 9, 7))              # shine
        p.setPen(QPen(QColor("#8a6a3a"), 2.5))
        p.drawLine(QPointF(s / 2, 5), QPointF(s / 2 + 7, 0))  # fuse
        if (self.fuse // 2) % 2 == 0:                       # sparkle
            p.setPen(QPen(QColor("#ffcf33"), 2))
            for i in range(6):
                a = math.radians(i * 60 + self.fuse * 20)
                p.drawLine(QPointF(s / 2 + 7, 1), QPointF(s / 2 + 7 + 6 * math.cos(a), 1 + 6 * math.sin(a)))
        p.end()


class SandCastle(QWidget):
    """A sand castle she builds bit by bit. Click it and it crumbles (rude!)."""
    W, H = 130, 112
    SAND, DARK_SAND, EDGE = QColor("#e8c98a"), QColor("#c9a564"), QColor("#7a5a2e")

    def __init__(self, x, y, on_break, on_done):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | TOOL_FLAG
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)    # never steal your typing
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(self.W, self.H)
        self.on_break, self.on_done = on_break, on_done
        self.progress = 0.0          # 0 -> 1 while she builds
        self.broken = 0              # ticks since it was broken
        self.pieces = []
        self.grains = []
        self.move(int(x), int(y))
        self.show()

    def step(self):
        if self.broken:
            self.broken += 1
            for pc in self.pieces:
                pc["x"] += pc["vx"]
                pc["y"] += pc["vy"]
                pc["vy"] += 0.7
                pc["rot"] += pc["vr"]
        elif self.progress < 1.0:
            was = self.progress
            self.progress = min(1.0, self.progress + 1 / 200.0)   # about 8 seconds
            if random.random() < 0.5:                             # sand flying as she works
                self.grains.append([random.uniform(20, 110), random.uniform(50, 100),
                                    random.uniform(-1.5, 1.5), random.uniform(-3, -1)])
            if was < 1.0 <= self.progress:
                self.on_done()
        for g in self.grains:
            g[0] += g[2]
            g[1] += g[3]
            g[3] += 0.4
        self.grains = [g for g in self.grains if g[1] < self.H][-60:]
        self.update()

    def mousePressEvent(self, e):
        if self.broken or self.progress < 0.15:
            return
        self.broken = 1
        # the castle's chunks go flying and tumble down
        for cx, cy, w, h in ((20, 52, 26, 40), (52, 30, 28, 62), (86, 52, 26, 40), (30, 80, 70, 20)):
            self.pieces.append({"x": cx, "y": cy, "w": w, "h": h,
                                "vx": random.uniform(-3, 3), "vy": random.uniform(-6, -2),
                                "rot": 0.0, "vr": random.uniform(-12, 12)})
        for _ in range(40):
            self.grains.append([random.uniform(15, 115), random.uniform(30, 100),
                                random.uniform(-4, 4), random.uniform(-6, 0)])
        self.on_break()

    def block(self, p, x, y, w, h, merlons=0):
        """A sandy block, with little battlements on top if merlons > 0."""
        p.drawRect(QRectF(x, y, w, h))
        if merlons:
            mw = w / (merlons * 2 - 1)
            for i in range(merlons):
                p.drawRect(QRectF(x + i * 2 * mw, y - 7, mw, 7))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(self.EDGE, 2))
        p.setBrush(QBrush(self.SAND))
        k = self.progress
        base = self.H - 8
        if not self.broken:
            p.drawChord(QRectF(4, base - 26, self.W - 8, 52), 0, 180 * 16)     # the mound
            if k > 0.2:                      # left tower
                t = min(1.0, (k - 0.2) / 0.2)
                self.block(p, 20, base - 12 - 40 * t, 26, 40 * t, 3 if t >= 1 else 0)
            if k > 0.4:                      # right tower
                t = min(1.0, (k - 0.4) / 0.2)
                self.block(p, 84, base - 12 - 40 * t, 26, 40 * t, 3 if t >= 1 else 0)
            if k > 0.6:                      # tall middle keep
                t = min(1.0, (k - 0.6) / 0.25)
                self.block(p, 50, base - 12 - 64 * t, 30, 64 * t, 3 if t >= 1 else 0)
                if t >= 1:                   # door + windows
                    p.setBrush(QBrush(self.DARK_SAND))
                    p.drawChord(QRectF(58, base - 30, 14, 28), 0, 180 * 16)
                    p.drawRect(QRectF(58, base - 16, 14, 4))
                    p.drawEllipse(QRectF(61, base - 58, 8, 8))
                    p.drawRect(QRectF(29, base - 38, 8, 9))
                    p.drawRect(QRectF(93, base - 38, 8, 9))
            if k >= 1.0:                     # little flag on top
                p.setPen(QPen(self.EDGE, 2))
                p.drawLine(QPointF(65, base - 83), QPointF(65, base - 100))
                p.setPen(QPen(QColor("#1b1b1b"), 1.5))
                p.setBrush(QBrush(QColor("#ff6b9a")))
                p.drawPolygon(QPolygonF([QPointF(66, base - 100), QPointF(80, base - 95),
                                         QPointF(66, base - 90)]))
        else:
            p.drawChord(QRectF(10, self.H - 26, self.W - 20, 36), 0, 180 * 16)   # flattened pile
            alpha = max(0, 255 - self.broken * 8)
            for pc in self.pieces:
                p.save()
                p.translate(pc["x"] + pc["w"] / 2, pc["y"] + pc["h"] / 2)
                p.rotate(pc["rot"])
                c = QColor(self.SAND)
                c.setAlpha(alpha)
                e = QColor(self.EDGE)
                e.setAlpha(alpha)
                p.setPen(QPen(e, 2))
                p.setBrush(QBrush(c))
                p.drawRect(QRectF(-pc["w"] / 2, -pc["h"] / 2, pc["w"], pc["h"]))
                p.restore()
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(self.DARK_SAND))
        for g in self.grains:
            p.drawEllipse(QPointF(g[0], g[1]), 1.8, 1.8)
        p.end()


# ---- weather (Open-Meteo, free, no account needed) ----
# your city is set in Customize -> Personal settings (no city = no weather)
WEATHER_TIMES = ["09:00", "13:00", "18:00"]      # when she tells you the weather
COLD_F, HOT_F = 40, 88
COLD_C, HOT_C = 4, 31


def weather_words(code):
    if code == 0:
        return "clear and sunny", "\u2600\ufe0f"
    if code in (1, 2):
        return "partly cloudy", "\u26c5"
    if code == 3:
        return "cloudy", "\u2601\ufe0f"
    if code in (45, 48):
        return "foggy", "\U0001F32B\ufe0f"
    if code in (51, 53, 55, 56, 57):
        return "drizzly", "\U0001F326\ufe0f"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "rainy", "\U0001F327\ufe0f"
    if code in (71, 73, 75, 77, 85, 86):
        return "snowy", "\u2744\ufe0f"
    if code in (95, 96, 99):
        return "stormy", "\u26c8\ufe0f"
    return "a little mysterious", "\U0001F914"


FORTUNES = ["I see... snacks in your future!", "A pleasant surprise is coming your way~",
            "Your next d20 roll... will be a good one!", "Someone is thinking about you \u2665",
            "I see a cozy nap in your future.", "Big creative energy today! \u2728",
            "Beware of... laundry. Hehe.", "A new adventure is about to start!",
            "The stars say: drink some water!", "Good news is on its way~",
            "I see... a cat? Or a very fluffy cloud.", "Today is a great day to make something!"]
SPELLS = ["I cast Fireball! \U0001F525", "I cast Magic Missile! \u2728", "Roll for initiative!",
          "I attack the goblin! \u2694\ufe0f", "Stealth check... shhh~", "I cast Healing Word! \u2665",
          "I try to persuade the dragon!", "I cast Eldritch Blast! \U0001F49C", "Perception check!",
          "I cast Thunderwave! \u26a1"]
BOOP_LINES = ["Boop! >w<", "Hey, my nose! \u2665", "Beep boop!", "*boop* hehe", "B-boop?!"]
SHY_LINES = ["S-stop it... >///<", "Too many headpats... \u2665", "Eep! I'm getting shy~",
             "W-why are you so nice to me...", ">///<"]


class SoapBubble(QWidget):
    """A floaty bubble she blows. Click to pop it!"""

    def __init__(self, x, y, on_pop):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | TOOL_FLAG
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)    # never steal your typing
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.r = random.randint(14, 26)
        self.S = self.r * 2 + 16
        self.resize(self.S, self.S)
        self.x_, self.y_ = float(x), float(y)
        self.vx = random.uniform(-1.2, 1.2)
        self.vy = random.uniform(-1.6, -0.7)
        self.phase = random.uniform(0, 6.28)
        self.age = 0
        self.popped = 0
        self.on_pop = on_pop
        self.move(int(self.x_), int(self.y_))
        self.show()

    def step(self):
        self.age += 1
        if self.popped:
            self.popped += 1
        else:
            self.x_ += self.vx + math.sin(self.age / 9 + self.phase) * 0.8
            self.y_ += self.vy
            self.move(int(self.x_), int(self.y_))
        self.update()

    def finished(self):
        return self.popped > 8 or self.age > 260

    def mousePressEvent(self, e):
        if not self.popped:
            self.popped = 1
            self.on_pop()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.S / 2
        if self.popped:                      # a little burst of droplets
            k = self.popped / 8.0
            p.setPen(QPen(QColor(150, 200, 255, int(220 * (1 - k))), 2))
            for i in range(8):
                a = math.radians(i * 45)
                r1, r2 = self.r * (0.6 + k), self.r * (0.9 + k)
                p.drawLine(QPointF(c + r1 * math.cos(a), c + r1 * math.sin(a)),
                           QPointF(c + r2 * math.cos(a), c + r2 * math.sin(a)))
            p.end()
            return
        hue = (self.age * 3 + self.phase * 40) % 360
        rim = QColor.fromHsv(int(hue), 120, 255, 200)
        p.setPen(QPen(rim, 2))
        p.setBrush(QBrush(QColor(200, 230, 255, 45)))
        p.drawEllipse(QPointF(c, c), self.r, self.r)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(255, 255, 255, 190)))
        p.drawEllipse(QPointF(c - self.r * 0.4, c - self.r * 0.4), self.r * 0.22, self.r * 0.15)
        p.end()


class CrystalBall(QWidget):
    """Her magic crystal ball: swirly mist and sparkles. Click it for a new fortune."""
    W, H = 96, 108

    def __init__(self, x, y, on_click):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | TOOL_FLAG
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)    # never steal your typing
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(self.W, self.H)
        self.on_click = on_click
        self.t = 0
        self.move(int(x), int(y))
        self.show()

    def step(self):
        self.t += 1
        self.update()

    def mousePressEvent(self, e):
        self.on_click()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = QColor("#1b1b1b")
        cx, cy, r = self.W / 2, 44, 36
        # glow
        glow = 0.5 + 0.5 * math.sin(self.t / 10)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(190, 140, 255, int(40 + 50 * glow))))
        p.drawEllipse(QPointF(cx, cy), r + 8, r + 8)
        # stand
        p.setPen(QPen(dark, 2))
        p.setBrush(QBrush(QColor("#c9a43c")))
        p.drawPolygon(QPolygonF([QPointF(cx - 26, self.H - 4), QPointF(cx + 26, self.H - 4),
                                 QPointF(cx + 16, cy + r - 6), QPointF(cx - 16, cy + r - 6)]))
        # orb
        p.setBrush(QBrush(QColor(120, 80, 200, 210)))
        p.drawEllipse(QPointF(cx, cy), r, r)
        # swirling mist
        p.setPen(Qt.NoPen)
        for i in range(5):
            a = self.t / 18 + i * 1.256
            mx = cx + math.cos(a) * r * 0.45
            my = cy + math.sin(a * 1.3) * r * 0.35
            p.setBrush(QBrush(QColor(230, 200, 255, 90)))
            p.drawEllipse(QPointF(mx, my), 11, 8)
        # sparkles
        p.setPen(QPen(QColor(255, 255, 255, 230), 1.5))
        for i in range(4):
            a = self.t / 7 + i * 1.57
            sx = cx + math.cos(a) * r * 0.6
            sy = cy + math.sin(a) * r * 0.5
            p.drawLine(QPointF(sx - 3, sy), QPointF(sx + 3, sy))
            p.drawLine(QPointF(sx, sy - 3), QPointF(sx, sy + 3))
        p.setBrush(QBrush(QColor(255, 255, 255, 170)))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx - 13, cy - 14), 7, 5)
        p.end()


class Bouquet(QWidget):
    """A little bunch of flowers she picked for you. Click to take them!"""
    W, H = 86, 104
    COLORS = ["#ff8fb8", "#ffd54f", "#a99be0", "#7fd1ff", "#ff9f6b"]

    def __init__(self, x, y, on_take):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | TOOL_FLAG
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)    # never steal your typing
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(self.W, self.H)
        self.on_take = on_take
        self.cols = random.sample(self.COLORS, 3)
        self.taken = 0
        self.pop = 0
        self.move(int(x), int(y))
        self.show()

    def step(self):
        if self.pop < 10:
            self.pop += 1
        if self.taken:
            self.taken += 1
            self.move(self.x(), self.y() - 3)
        self.update()

    def mousePressEvent(self, e):
        if not self.taken:
            self.taken = 1
            self.on_take()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.taken:
            p.setOpacity(max(0.0, 1 - self.taken / 25))
        k = min(1.0, 0.3 + self.pop / 10 * 0.7)
        p.translate(self.W / 2, self.H)
        p.scale(k, k)
        p.translate(-self.W / 2, -self.H)
        dark = QColor("#1b1b1b")
        p.setPen(QPen(QColor("#4f9a4a"), 3))
        heads = [(26, 34), (43, 22), (60, 34)]
        for hx, hy in heads:
            p.drawLine(QPointF(43, 84), QPointF(hx, hy))
        for (hx, hy), col in zip(heads, self.cols):
            p.setPen(QPen(dark, 1.5))
            p.setBrush(QBrush(QColor(col)))
            for i in range(5):
                a = math.radians(i * 72 - 90)
                p.drawEllipse(QPointF(hx + 8 * math.cos(a), hy + 8 * math.sin(a)), 7, 7)
            p.setBrush(QBrush(QColor("#fff3c4")))
            p.drawEllipse(QPointF(hx, hy), 5, 5)
        # ribbon
        p.setPen(QPen(dark, 1.5))
        p.setBrush(QBrush(QColor("#e8636f")))
        p.drawEllipse(QPointF(36, 82), 8, 5)
        p.drawEllipse(QPointF(50, 82), 8, 5)
        p.drawRect(QRectF(39, 78, 8, 9))
        p.end()


CUSTOM_FILE = os.path.expanduser("~/.desk_pet_custom.json")
# hair styles (just styles - anyone can wear any of them). More styles can be added later.
HAIR_STYLES = [("twintails", "Twin tails"), ("shorttails", "Short tails"), ("drills", "Drill tails"),
               ("shaggy", "Shaggy"), ("swept", "Swept bangs")]
# what she wears below the belt; each is a separate rendered layer (pet_frames/bottom_<key>/)
BOTTOMS = [("skirt", "Skirt"), ("shorts", "Shorts")]
# The hair color palette (name, hex). "Original" keeps her rendered hair.
HAIR_COLORS = [
    ("Star Grass", "#70E2CB"), ("Twilight Periwinkle", "#615E9B"), ("Misted Lavender", "#A08BCB"),
    ("Sheer Lilac", "#B996C3"), ("Muted Rose Quartz", "#DCA9BF"), ("Caribbean Green", "#00C795"),
    ("Lyrebird", "#0087AE"), ("Fuchsia Felicity", "#EF426F"), ("Quiche Lorraine", "#FDD26E"),
    ("Dark Vivid Cyan", "#003E51"), ("Light Template", "#BDD6EB"), ("Frosty Sky", "#9BC7EE"),
    ("Lavender Thistle", "#C7B2DE"), ("Dahlia Delight", "#F8BED6"), ("Heartfelt", "#FBA9C4"),
]


# Digi's room (Nancy's drawing) behind the Customize window; the settings live on the phone's screen.
ROOM_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "digi_room.png")
ROOM_SIZE = (2000, 1500)                 # the drawing's size; spots below are in its pixels
ROOM_SCREEN = (1292, 196, 532, 1150)     # the phone's white screen: x, y, w, h
ROOM_DIGI = (700, 1400, 940) 
ROOM_TILT = 0                            # degrees to tilt the phone's settings (1.5 matches the drawing's lean;
                                         # Nancy liked them straight better)            # where Digi stands on the rug: center x, feet y, height


class FlowLayout(QLayout):
    """Buttons that wrap onto the next line when the phone screen is narrow."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self.items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def addWidget(self, w, *args, **kw):         # grid positions / stretch are ignored: it just flows
        super().addWidget(w)

    def addStretch(self, *a):
        pass

    def addSpacing(self, *a):
        pass

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.place(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.place(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self.items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def place(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        gap = self.spacing()
        for it in self.items:
            hint = it.sizeHint()
            w = min(hint.width(), rect.width())
            if x + w > rect.right() + 1 and line_h > 0:
                x = rect.x()
                y += line_h + gap
                line_h = 0
            h = it.heightForWidth(w) if it.hasHeightForWidth() else hint.height()
            h = max(h, hint.height()) if not it.hasHeightForWidth() else h
            if not test:
                it.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
            x += w + gap
            line_h = max(line_h, h)
        return y + line_h - rect.y()


class CustomizeDialog(QDialog):
    """Shift+click her (or right-click -> Customize Digi...) to dress her up."""

    def __init__(self, pet):
        super().__init__(None)
        self.pet = pet
        self.setWindowTitle("Customize Digi")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.room = QPixmap(ROOM_FILE) if os.path.exists(ROOM_FILE) else QPixmap()
        self.in_room = not self.room.isNull()
        self.anim_k = 0
        self.anim = QTimer(self)
        self.anim.setInterval(110)
        self.anim.timeout.connect(self.anim_step)
        self.setStyleSheet("""
            QDialog { background: #f6f3fb; }
            QLabel#h { font-weight: bold; font-size: 13px; color: #4b3f7a; margin-top: 6px; }
            QPushButton[class="sw"] { border: 2px solid #ffffff; border-radius: 15px; min-width: 30px;
                             max-width: 30px; min-height: 30px; max-height: 30px; }
            QPushButton[class="sw"]:checked { border: 3px solid #1b1b1b; }
            QDialog QLabel { color: #3a3159; }
            QPushButton[class="opt"] { padding: 5px 10px; border-radius: 8px; border: 1px solid #c9bfe3;
                              background: white; color: #3a3159; }
            QPushButton[class="opt"]:hover { background: #efeaf9; }
            QPushButton[class="opt"]:checked { background: #a99be0; color: white; border-color: #6b5f93; }
            QPushButton[class="opt"]:disabled { color: #b3abc9; }
        """)
        look = QWidget()
        # small laptop screens: let the Look tab scroll instead of squishing rows on top of each other
        look_scroll = QScrollArea()
        look_scroll.setWidgetResizable(True)
        look_scroll.setFrameShape(QFrame.NoFrame)
        look_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        look_scroll.setWidget(look)
        personal_scroll = QScrollArea()          # scrolls on small screens, like the Look tab
        personal_scroll.setWidgetResizable(True)
        personal_scroll.setFrameShape(QFrame.NoFrame)
        personal_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        personal_scroll.setWidget(self.build_personal())
        med_scroll = QScrollArea()               # the Meditation tab
        med_scroll.setWidgetResizable(True)
        med_scroll.setFrameShape(QFrame.NoFrame)
        med_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        med_scroll.setWidget(self.build_meditation())
        lists_scroll = QScrollArea()             # the Lists tab: water, to-dos, reminders, birthdays
        lists_scroll.setWidgetResizable(True)
        lists_scroll.setFrameShape(QFrame.NoFrame)
        lists_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lists_scroll.setWidget(self.build_lists())
        dnd_scroll = QScrollArea()               # the D&D tab: games, initiative, notes
        dnd_scroll.setWidgetResizable(True)
        dnd_scroll.setFrameShape(QFrame.NoFrame)
        dnd_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        dnd_scroll.setWidget(self.build_dnd())
        # live preview of her
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        if self.in_room:
            # the room is painted behind everything; Digi stands on the rug, settings go on the phone
            self.preview.setParent(self)
            self.preview.setStyleSheet("background: transparent;")
            self.preview.setAttribute(Qt.WA_TransparentForMouseEvents)
            for sc in (look_scroll, personal_scroll, med_scroll, lists_scroll, dnd_scroll):
                sc.setStyleSheet("QScrollArea { background: white; border: none; } "
                                 "QScrollArea > QWidget > QWidget { background: white; }")
            self.phone = QWidget(None if ROOM_TILT else self)
            self.phone.setObjectName("phone")
        if self.in_room and ROOM_TILT:
            # tilted: the phone's real buttons live in a tiny graphics scene that's turned by
            # ROOM_TILT degrees (clicks and scrolling still work)
            self.phone_scene = QGraphicsScene(self)
            self.phone_proxy = self.phone_scene.addWidget(self.phone)
            self.phone_view = QGraphicsView(self.phone_scene, self)
            self.phone_view.setFrameShape(QFrame.NoFrame)
            self.phone_view.setStyleSheet("QGraphicsView { background: transparent; border: none; }")
            self.phone_view.viewport().setAutoFillBackground(False)
            self.phone_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.phone_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.phone_view.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self.phone_view.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing
                                           | QPainter.SmoothPixmapTransform)
        if self.in_room:
            self.phone.setStyleSheet("QWidget#phone { background: white; }")
            pl = QVBoxLayout(self.phone)
            pl.setContentsMargins(4, 0, 4, 6)
            pl.setSpacing(4)
            self.phone_title = QLabel("Customize Digi")
            self.phone_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #3d4f75;")
            pl.addWidget(self.phone_title)
            self.pages = QStackedWidget()
            self.pages.addWidget(look_scroll)
            self.pages.addWidget(personal_scroll)
            self.pages.addWidget(med_scroll)
            self.pages.addWidget(lists_scroll)
            self.pages.addWidget(dnd_scroll)
            pl.addWidget(self.pages, 1)
            dock = QHBoxLayout()
            dock.setSpacing(4)
            self.dock_buttons = []
            for i, label in enumerate(("Look", "Me", "Calm", "Lists", "Game night")):
                b = QPushButton(label)
                b.setCheckable(True)
                b.setProperty("class", "dock")
                b.clicked.connect(lambda *a, i=i: self.show_page(i))
                self.dock_buttons.append(b)
                dock.addWidget(b)
            done = QPushButton("Done")
            done.setProperty("class", "done")
            done.clicked.connect(self.accept)
            dock.addWidget(done)
            pl.addSpacing(10)                # a little breathing room above the buttons
            pl.addLayout(dock)
            self.show_page(0)
            self.room_bubble = RoomBubble(pet, self)
            col = QVBoxLayout(look)
            col.setContentsMargins(2, 2, 6, 2)
        else:
            for sc in (look_scroll, personal_scroll, med_scroll, lists_scroll, dnd_scroll):
                sc.setStyleSheet("QScrollArea { background: transparent; } "
                                 "QScrollArea > QWidget > QWidget { background: #f6f3fb; }")
            main = QVBoxLayout(self)
            tabs = QTabWidget()
            tabs.setStyleSheet("QTabBar::tab { padding: 6px 14px; color: #3a3159; background: #ece8f5; "
                               "border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px; }"
                               "QTabBar::tab:selected { background: #a99be0; color: white; }"
                               "QTabWidget::pane { border: none; }")
            main.addWidget(tabs)
            tabs.addTab(look_scroll, "Look")
            tabs.addTab(personal_scroll, "Personal settings")
            tabs.addTab(med_scroll, "Meditation")
            tabs.addTab(lists_scroll, "Lists")
            tabs.addTab(dnd_scroll, "Game night")
            tabs.currentChanged.connect(lambda i: self.refresh_dnd() if i == 4 else None)
            self.tabs = tabs
            outer = QHBoxLayout(look)
            self.preview.setFixedSize(220, 260)
            self.preview.setStyleSheet("background: #ece8f5; border-radius: 12px;")
            outer.addWidget(self.preview)
            col = QVBoxLayout()
            outer.addLayout(col)

        # outline: a soft glow around her so she doesn't vanish on dark windows (first, so it's easy to find)
        col.addWidget(self.heading("Glow outline"))
        row = self.hrow()
        self.outline_buttons = {}
        for key, label in (("glow", "Glow \u2728"), ("off", "Off")):
            b = self.option(label)
            b.clicked.connect(lambda *a, k=key: self.pick_outline(k))
            self.outline_buttons[key] = b
            row.addWidget(b)
        tip = QLabel("Glow so I don't get lost in dark mode!")
        tip.setStyleSheet("background: white; color: #4b3f7a; border: 1px solid #c9bfe3; "
                          "border-radius: 10px; padding: 4px 10px; font-size: 12px;")
        tip.setWordWrap(True)
        if self.in_room:
            col.addLayout(row)
            col.addWidget(tip)          # on its own line on the phone
        else:
            row.addSpacing(6)
            row.addWidget(tip)
            row.addStretch(1)
            col.addLayout(row)

        # hair style
        col.addWidget(self.heading("Hair style"))
        hg = self.gridl()
        self.style_hair_buttons = {}
        for i, (key, label) in enumerate(HAIR_STYLES):
            b = self.option(label)
            b.clicked.connect(lambda *a, k=key: self.pick_hairstyle(k))
            self.style_hair_buttons[key] = b
            hg.addWidget(b, i // 3, i % 3)
        col.addLayout(hg)

        # skirt or shorts
        col.addWidget(self.heading("Bottoms"))
        row = self.hrow()
        self.bottom_buttons = {}
        for key, label in BOTTOMS:
            b = self.option(label)
            b.clicked.connect(lambda *a, k=key: self.pick_bottom(k))
            self.bottom_buttons[key] = b
            row.addWidget(b)
        row.addStretch(1)
        col.addLayout(row)

        # speech bubble: light (white bubble, black text) or dark (black bubble, white text)
        col.addWidget(self.heading("Speech bubble"))
        row = self.hrow()
        self.bubble_buttons = {}
        for key, label in (("light", "Light"), ("dark", "Dark")):
            b = self.option(label)
            b.clicked.connect(lambda *a, k=key: self.pick_bubble(k))
            self.bubble_buttons[key] = b
            row.addWidget(b)
        row.addSpacing(10)
        self.shape_buttons = {}
        for key, label in (("speech", "Speech \U0001F4AC"), ("thought", "Thought \U0001F4AD")):
            b = self.option(label)
            b.clicked.connect(lambda *a, k=key: self.pick_bubble_shape(k))
            self.shape_buttons[key] = b
            row.addWidget(b)
        row.addStretch(1)
        col.addLayout(row)
        row = self.hrow()
        self.spot_buttons = {}
        for key, label in (("above", "Above her head"), ("side", "Next to her")):
            b = self.option(label)
            b.clicked.connect(lambda *a, k=key: self.pick_bubble_pos(k))
            self.spot_buttons[key] = b
            row.addWidget(b)
        row.addStretch(1)
        col.addLayout(row)
        row = self.hrow()
        self.textsize_buttons = {}
        for key, label in (("small", "Small text"), ("medium", "Medium text"), ("large", "Big text")):
            b = self.option(label)
            b.clicked.connect(lambda *a, k=key: self.pick_textsize(k))
            self.textsize_buttons[key] = b
            row.addWidget(b)
        row.addStretch(1)
        col.addLayout(row)

        # hair
        col.addWidget(self.heading("Hair color"))
        grid = self.gridl()
        grid.setSpacing(6)
        self.swatches = {}
        orig = self.option("Original")
        orig.clicked.connect(lambda *a: self.pick_hair(None))
        self.swatches[None] = orig
        grid.addWidget(orig, 0, 0, 1, 3)
        for i, (name, hx) in enumerate(HAIR_COLORS):
            b = QPushButton()
            b.setProperty("class", "sw")
            b.setCheckable(True)
            b.setToolTip(name)
            b.setStyleSheet("background: %s;" % hx)
            b.clicked.connect(lambda *a, h=hx: self.pick_hair(h))
            self.swatches[hx] = b
            grid.addWidget(b, 1 + i // 5, i % 5)
        anyc = self.option("Any color...")
        anyc.setCheckable(False)
        anyc.clicked.connect(self.pick_any)
        grid.addWidget(anyc, 0, 3, 1, 2)
        col.addLayout(grid)

        # outfit
        col.addWidget(self.heading("Outfit"))
        og = self.gridl()
        self.outfit_buttons = {}
        for i, (key, label) in enumerate(ACC_MENU):
            b = self.option(label.replace(" (changes by month)", ""))
            b.clicked.connect(lambda *a, k=key: self.pick_outfit(k))
            self.outfit_buttons[key] = b
            og.addWidget(b, i // 4, i % 4)
        col.addLayout(og)
        srow = self.hrow()
        self.style_buttons = {}
        for key, label in (("3d", "3D outfits"), ("drawn", "Drawn outfits")):
            b = self.option(label)
            b.clicked.connect(lambda *a, k=key: self.pick_style(k))
            self.style_buttons[key] = b
            srow.addWidget(b)
        srow.addStretch(1)
        col.addLayout(srow)

        col.addStretch(1)
        if self.in_room:
            self.setStyleSheet(self.styleSheet() + """
                QDialog { background: #e1ebdf; }
                QLabel#h { color: #3d4f75; font-size: 12px; margin-top: 3px; }
                QDialog QLabel { font-size: 11px; }
                QPushButton[class="opt"] { padding: 2px 6px; border-radius: 7px; border-color: #b8c5dc;
                                           font-size: 11px; }
                QPushButton[class="sw"] { border-radius: 11px; min-width: 22px; max-width: 22px;
                                          min-height: 22px; max-height: 22px; }
                QPushButton[class="sw"]:checked { border: 2px solid #1b1b1b; }
                QComboBox, QSpinBox, QLineEdit, QTimeEdit { font-size: 11px; }
                QCheckBox { font-size: 11px; color: #3d4f75; }
                QPushButton[class="opt"]:hover { background: #eef2f9; }
                QPushButton[class="opt"]:checked { background: #7389b0; border-color: #4e6590; color: white; }
                QPushButton[class="dock"] { padding: 4px 2px; font-size: 11px; border-radius: 10px; border: 1px solid #b8c5dc;
                                            background: #f3f6fb; color: #3d4f75; font-weight: bold; }
                QPushButton[class="dock"]:checked { background: #dfe7f4; border-color: #7389b0; }
                QPushButton[class="done"] { padding: 4px 2px; font-size: 11px; border-radius: 10px; border: 1px solid #4e6590;
                                            background: #7389b0; color: white; font-weight: bold; }
                QPushButton[class="done"]:hover { background: #637aa3; }
            """)
            self.phone.setStyleSheet(self.styleSheet() + " QWidget#phone { background: white; }")
        else:
            done = QPushButton("Done")
            done.setStyleSheet("QPushButton { padding: 6px 22px; border-radius: 8px; background: #a99be0; "
                               "color: white; border: 1px solid #6b5f93; font-weight: bold; }"
                               "QPushButton:hover { background: #9483d6; }")
            done.clicked.connect(self.accept)
            main.addWidget(done, alignment=Qt.AlignRight)
        self.refresh()
        try:
            scr = (pet.screen() if pet is not None else None) or QApplication.primaryScreen()
            avail = scr.availableGeometry()
            if self.in_room:
                # the room keeps its shape: as big as fits (up to 1100 wide)
                rw, rh = ROOM_SIZE
                k = min(1100 / rw, (avail.width() - 40) / rw, (avail.height() - 60) / rh)
                self.setFixedSize(int(rw * k), int(rh * k))
            else:
                # as big as everything needs, but never taller than the screen (then the Look tab scrolls)
                want = look.sizeHint()
                self.resize(min(want.width() + 60, avail.width() - 40),
                            min(want.height() + 110, avail.height() - 60))
        except Exception as ex:
            print("customize size:", ex, file=sys.stderr, flush=True)

    # ---------- the room ----------
    # ---------- the Lists tab: everything you keep track of with her, in one place ----------
    def list_box(self, rows=4):
        lw = QListWidget()
        lw.setStyleSheet("QListWidget { border: 1px solid #ddd5ef; border-radius: 8px; background: white; "
                         "color: #3a3159; } QListWidget::item { padding: 3px 4px; } "
                         "QListWidget::item:selected { background: #efeaf9; color: #3a3159; }")
        lw.setFixedHeight(24 * rows + 8)
        return lw

    def small_buttons(self, specs):
        row = QHBoxLayout()
        row.setSpacing(4)
        for label, fn in specs:
            b = self.option(label)
            b.setCheckable(False)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        return row

    def build_lists(self):
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(2, 2, 6, 2)
        pet = self.pet

        # water
        col.addWidget(self.heading("Water \U0001F4A7"))
        self.water_label = QLabel()
        col.addWidget(self.water_label)
        col.addLayout(self.small_buttons([("+1 glass", lambda *a: (pet.drink(), self.refresh_lists())),
                                          ("Undo", lambda *a: (pet.undrink(), self.refresh_lists()))]))
        wrow = QHBoxLayout()
        wrow.addWidget(QLabel("Daily goal:"))
        self.water_goal = QSpinBox()
        self.water_goal.setRange(1, 30)
        self.water_goal.valueChanged.connect(self.set_water_goal)
        wrow.addWidget(self.water_goal)
        wrow.addWidget(QLabel("glasses"))
        wrow.addStretch(1)
        col.addLayout(wrow)

        # to-do list
        col.addWidget(self.heading("To-do list \u2705"))
        tip = QLabel("Tick a task when it's done!")
        tip.setStyleSheet("color: #6b5f93; font-size: 11px;")
        col.addWidget(tip)
        self.todo_list = self.list_box(4)
        self.todo_list.itemChanged.connect(self.todo_ticked)
        col.addWidget(self.todo_list)
        trow = QHBoxLayout()
        self.todo_text = QLineEdit()
        self.todo_text.setPlaceholderText("New task...")
        self.todo_text.setMaxLength(80)
        self.todo_text.returnPressed.connect(self.todo_add)
        trow.addWidget(self.todo_text, 1)
        add = self.option("Add")
        add.setCheckable(False)
        add.clicked.connect(self.todo_add)
        trow.addWidget(add)
        col.addLayout(trow)

        # reminders
        col.addWidget(self.heading("Reminders \u23F0"))
        self.rem_list = self.list_box(5)
        self.rem_list.itemDoubleClicked.connect(lambda *_: self.rem_edit())
        col.addWidget(self.rem_list)
        col.addLayout(self.small_buttons([("Add", self.rem_add), ("Change", self.rem_edit),
                                          ("Delete", self.rem_delete)]))

        # birthdays
        col.addWidget(self.heading("Birthdays \U0001F382"))
        self.bday_list = self.list_box(3)
        self.bday_list.itemDoubleClicked.connect(lambda *_: self.bday_edit())
        col.addWidget(self.bday_list)
        col.addLayout(self.small_buttons([("Add", self.bday_add), ("Change", self.bday_edit),
                                          ("Delete", self.bday_delete)]))

        # cycle tracker: hidden unless it's switched on (the switch is the small box at the bottom)
        self.cycle_box = QWidget()
        cl = QVBoxLayout(self.cycle_box)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.heading("Cycle \U0001F338"))
        self.cycle_label = QLabel()
        self.cycle_label.setWordWrap(True)
        cl.addWidget(self.cycle_label)
        cl.addLayout(self.small_buttons([("Started today", lambda *a: self.cycle_mark(date.today())),
                                         ("Other day...", self.cycle_pick_day),
                                         ("Undo", self.cycle_undo)]))
        crow = QHBoxLayout()
        crow.addWidget(QLabel("Usually lasts"))
        self.cycle_len = QSpinBox()
        self.cycle_len.setRange(1, 14)
        self.cycle_len.valueChanged.connect(lambda v: self.cycle_set("period_len", v))
        crow.addWidget(self.cycle_len)
        crow.addWidget(QLabel("days"))
        crow.addStretch(1)
        cl.addLayout(crow)
        self.cycle_notify = QCheckBox("Gentle heads-ups from Digi (never while streaming)")
        self.cycle_notify.toggled.connect(lambda v: self.cycle_set("notify", v))
        cl.addWidget(self.cycle_notify)
        note = QLabel("Her guesses come from your past cycles, so they're just estimates. "
                      "Everything stays only on this computer.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #6b5f93; font-size: 11px;")
        cl.addWidget(note)
        col.addWidget(self.cycle_box)

        col.addWidget(self.heading("My trivia \u270F\ufe0f"))
        lab = QLabel("Write your own questions (campaign lore, your channel, your stories...). "
                     "Play them with Play \u2192 Trivia \u2192 Mine.")
        lab.setWordWrap(True)
        lab.setStyleSheet("color: #6b5f93; font-size: 11px;")
        col.addWidget(lab)
        self.trivia_list = self.list_box(4)
        self.trivia_list.itemDoubleClicked.connect(lambda *_: self.trivia_edit())
        col.addWidget(self.trivia_list)
        col.addLayout(self.small_buttons([("Add", self.trivia_add), ("Change", self.trivia_edit),
                                          ("Delete", self.trivia_delete)]))
        col.addSpacing(8)
        self.cycle_on = QCheckBox("Show cycle tracker \U0001F338")
        self.cycle_on.setStyleSheet("color: #8a80aa; font-size: 11px;")
        self.cycle_on.toggled.connect(self.cycle_toggle)
        col.addWidget(self.cycle_on)
        col.addStretch(1)
        return w

    def refresh_lists(self):
        pet = self.pet
        if not hasattr(self, "todo_list"):
            return
        n = pet.water_today()
        self.water_label.setText(f"Today: {n} of {pet.water['goal']} glasses " + "\U0001F4A7" * min(n, 10))
        self.water_goal.blockSignals(True)
        self.water_goal.setValue(pet.water["goal"])
        self.water_goal.blockSignals(False)
        self.todo_list.blockSignals(True)
        self.todo_list.clear()
        for t in pet.todos:
            it = QListWidgetItem(t)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            self.todo_list.addItem(it)
        if not pet.todos:
            it = QListWidgetItem("(nothing yet!)")
            it.setFlags(Qt.NoItemFlags)
            self.todo_list.addItem(it)
        self.todo_list.blockSignals(False)
        pet.reminders.sort(key=lambda r: r[0])
        self.rem_list.clear()
        for r in pet.reminders:
            self.rem_list.addItem(QListWidgetItem(reminder_label(r)))
        pet.birthdays.sort(key=lambda b: days_until_birthday(b["month"], b["day"]))
        self.bday_list.clear()
        for b in pet.birthdays:
            n = days_until_birthday(b["month"], b["day"])
            when = "today!" if n == 0 else ("tomorrow" if n == 1 else f"in {n} days")
            self.bday_list.addItem(QListWidgetItem(f"{birthday_label(b)}   ({when})"))
        c = pet.cycle
        self.cycle_on.blockSignals(True)
        self.cycle_on.setChecked(bool(c.get("enabled")))
        self.cycle_on.blockSignals(False)
        self.cycle_box.setVisible(bool(c.get("enabled")))
        self.cycle_len.blockSignals(True)
        self.cycle_len.setValue(int(c.get("period_len", 5)))
        self.cycle_len.blockSignals(False)
        self.cycle_notify.blockSignals(True)
        self.cycle_notify.setChecked(bool(c.get("notify", True)))
        self.cycle_notify.blockSignals(False)
        self.cycle_label.setText(pet.cycle_summary())
        self.trivia_list.clear()
        for t in pet.trivia_mine:
            self.trivia_list.addItem(f"{t['q']}  \u2192  {t['a']}")
        if not pet.trivia_mine:
            it = QListWidgetItem("(no questions yet!)")
            it.setFlags(Qt.NoItemFlags)
            self.trivia_list.addItem(it)

    def trivia_add(self):
        dlg = TriviaEdit(self)
        if dlg.exec():
            item = dlg.result_item()
            if item:
                self.pet.trivia_mine.append(item)
                self.pet.save_custom()
                self.refresh_lists()

    def trivia_edit(self):
        i = self.trivia_list.currentRow()
        if i < 0 or i >= len(self.pet.trivia_mine):
            return
        dlg = TriviaEdit(self, self.pet.trivia_mine[i])
        if dlg.exec():
            item = dlg.result_item()
            if item:
                self.pet.trivia_mine[i] = item
                self.pet.save_custom()
                self.refresh_lists()

    def trivia_delete(self):
        i = self.trivia_list.currentRow()
        if i < 0 or i >= len(self.pet.trivia_mine):
            return
        t = self.pet.trivia_mine[i]
        if QMessageBox.question(self, "Delete question",
                                f"Delete this question?\n\n{t['q']}\n\u2192 {t['a']}") == QMessageBox.Yes:
            del self.pet.trivia_mine[i]
            self.pet.save_custom()
            self.refresh_lists()

    def set_water_goal(self, n):
        self.pet.water["goal"] = n
        self.pet.save_water()
        self.refresh_lists()

    def todo_add(self):
        t = self.todo_text.text().strip()
        if not t:
            return
        self.pet.todos.append(t[:80])
        self.pet.save_todos()
        self.pet.say("Added! You've got this~", 2200)
        self.pet.happy = 15
        self.todo_text.clear()
        self.refresh_lists()

    def todo_ticked(self, item):
        if item.checkState() == Qt.Checked:
            i = self.todo_list.row(item)
            QTimer.singleShot(250, lambda: (self.pet.finish_todo(i), self.refresh_lists()))

    def rem_add(self):
        dlg = ReminderEdit(self)
        if dlg.exec():
            self.pet.reminders.append(dlg.result_item())
            save_reminders(self.pet.reminders)
            self.refresh_lists()

    def rem_edit(self):
        i = self.rem_list.currentRow()
        if i < 0:
            return
        dlg = ReminderEdit(self, self.pet.reminders[i])
        if dlg.exec():
            self.pet.reminders[i] = dlg.result_item()
            save_reminders(self.pet.reminders)
            self.refresh_lists()

    def rem_delete(self):
        i = self.rem_list.currentRow()
        if i < 0:
            return
        r = self.pet.reminders[i]
        if QMessageBox.question(self, "Delete reminder",
                                "Delete this reminder?\n\n" + reminder_label(r)) == QMessageBox.Yes:
            del self.pet.reminders[i]
            save_reminders(self.pet.reminders)
            self.refresh_lists()

    def bday_add(self):
        dlg = BirthdayEdit(self)
        if dlg.exec():
            b = dlg.result_item()
            self.pet.birthdays.append(b)
            self.pet.save_custom()
            self.pet.say(f"Got it! I'll remember {b['name']}'s birthday \U0001F382", 3000)
            self.refresh_lists()

    def bday_edit(self):
        i = self.bday_list.currentRow()
        if i < 0:
            return
        dlg = BirthdayEdit(self, self.pet.birthdays[i])
        if dlg.exec():
            self.pet.birthdays[i] = dlg.result_item()
            self.pet.save_custom()
            self.refresh_lists()

    def bday_delete(self):
        i = self.bday_list.currentRow()
        if i < 0:
            return
        b = self.pet.birthdays[i]
        if QMessageBox.question(self, "Delete birthday",
                                "Forget this birthday?\n\n" + birthday_label(b)) == QMessageBox.Yes:
            del self.pet.birthdays[i]
            self.pet.save_custom()
            self.refresh_lists()

    def cycle_toggle(self, on):
        self.pet.cycle["enabled"] = bool(on)
        self.pet.save_cycle()
        self.refresh_lists()

    def cycle_set(self, key, value):
        self.pet.cycle[key] = value
        self.pet.save_cycle()
        self.refresh_lists()

    def cycle_mark(self, day):
        self.pet.cycle_started(day)
        self.refresh_lists()

    def cycle_pick_day(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("When did it start?")
        lay = QVBoxLayout(dlg)
        cal = QCalendarWidget()
        cal.setMaximumDate(QDate.currentDate())
        lay.addWidget(cal)
        ok = QPushButton("Save")
        ok.clicked.connect(dlg.accept)
        lay.addWidget(ok)
        if dlg.exec():
            d = cal.selectedDate()
            self.cycle_mark(date(d.year(), d.month(), d.day()))

    def cycle_undo(self):
        if self.pet.cycle.get("starts"):
            self.pet.cycle["starts"].pop()
            self.pet.save_cycle()
        self.refresh_lists()

    # ---------- the D&D tab: your games, initiative and session notes ----------
    def build_dnd(self):
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(2, 2, 6, 2)
        pet = self.pet
        self.dnd_status = QLabel()
        self.dnd_status.setWordWrap(True)
        self.dnd_status.setStyleSheet("background: #efeaf9; color: #4b3f7a; border-radius: 10px; "
                                      "padding: 5px 9px; font-size: 12px;")
        col.addWidget(self.dnd_status)

        # games
        col.addWidget(self.heading("My game nights \U0001F3B2"))
        self.dnd_list = self.list_box(4)
        self.dnd_list.setWordWrap(True)
        self.dnd_list.itemDoubleClicked.connect(lambda *_: self.dnd_edit())
        col.addWidget(self.dnd_list)
        col.addLayout(self.small_buttons([("Add", self.dnd_add), ("Change", self.dnd_edit),
                                          ("Delete", self.dnd_delete)]))
        self.dnd_use_name = QCheckBox("During games, call me by my character's name")
        self.dnd_use_name.toggled.connect(lambda v: self.dnd_opt("use_name", v))
        col.addWidget(self.dnd_use_name)
        self.dnd_dress = QCheckBox("Dress up for games (GM: book, player: sword)")
        self.dnd_dress.toggled.connect(lambda v: self.dnd_opt("dress", v))
        col.addWidget(self.dnd_dress)

        # initiative
        col.addWidget(self.heading("Initiative \u2694\ufe0f"))
        orow = self.hrow()
        orow.addWidget(QLabel("Order:"))
        self.init_mode_buttons = {}
        for key, label in (("roll", "By rolls \U0001F3B2"), ("manual", "My own order \u270F\ufe0f")):
            b = self.option(label)
            b.clicked.connect(lambda *a, k=key: self.init_set_mode(k))
            self.init_mode_buttons[key] = b
            orow.addWidget(b)
        col.addLayout(orow)
        self.init_round = QLabel()
        self.init_round.setWordWrap(True)
        self.init_round.setStyleSheet("color: #6b5f93; font-size: 11px;")
        col.addWidget(self.init_round)
        self.init_list = self.list_box(5)
        col.addWidget(self.init_list)
        self.init_name = QLineEdit()
        self.init_name.setPlaceholderText("Who? (Goblin 1, Rainy...)")
        self.init_name.setMaxLength(24)
        self.init_name.returnPressed.connect(lambda: self.init_add())
        col.addWidget(self.init_name)
        self.init_roll_row = QWidget()
        irow = QHBoxLayout(self.init_roll_row)
        irow.setContentsMargins(0, 0, 0, 0)
        irow.addWidget(QLabel("Rolled"))
        self.init_roll = QSpinBox()
        self.init_roll.setRange(1, 30)
        self.init_roll.setValue(10)
        self.init_roll.setToolTip("What their d20 landed on")
        irow.addWidget(self.init_roll)
        irow.addWidget(QLabel("Modifier"))
        self.init_mod = ModSpin()
        self.init_mod.setRange(-10, 20)
        self.init_mod.setValue(0)
        self.init_mod.setToolTip("Their initiative bonus (like +2 for Dex). Digi adds it for you.")
        irow.addWidget(self.init_mod)
        irow.addStretch(1)
        col.addWidget(self.init_roll_row)
        brow = QHBoxLayout()
        brow.setSpacing(4)
        for label, fn, attr in (("Add", lambda *a: self.init_add(), None),
                                ("Add me", self.init_add_me, "init_me_btn"),
                                ("\U0001F3B2 Roll for them", self.init_d20, "init_d20_btn")):
            b = self.option(label)
            b.setCheckable(False)
            b.clicked.connect(fn)
            brow.addWidget(b)
            if attr:
                setattr(self, attr, b)
        brow.addStretch(1)
        col.addLayout(brow)
        col.addLayout(self.small_buttons([("Next turn \u25B6", self.init_next),
                                          ("\u25B2", lambda *a: self.init_move(-1)),
                                          ("\u25BC", lambda *a: self.init_move(1))]))
        col.addLayout(self.small_buttons([("Remove", self.init_remove),
                                          ("Clear all", self.init_clear)]))

        # notes
        col.addWidget(self.heading("Session notes \U0001F4DC"))
        col.addLayout(self.small_buttons([("Pop out \u2197 (keep it open while you play)",
                                           lambda *a: self.pet.open_dnd_notes(self.notes_game.currentIndex()))]))
        col.addLayout(self.small_buttons([("Export this game...", lambda *a: self.notes_export(False)),
                                          ("Export all games...", lambda *a: self.notes_export(True))]))
        self.notes_game = QComboBox()
        self.notes_game.currentIndexChanged.connect(self.notes_show)
        col.addWidget(self.notes_game)
        self.notes_box = QPlainTextEdit()
        self.notes_box.setPlaceholderText("NPC names, loot, what happened last time...")
        self.notes_box.setStyleSheet("QPlainTextEdit { border: 1px solid #ddd5ef; border-radius: 8px; "
                                     "background: white; color: #3a3159; }")
        self.notes_box.setMinimumHeight(140)
        self.notes_box.textChanged.connect(self.notes_changed)
        col.addWidget(self.notes_box)
        note = QLabel("Your games and notes stay only on this computer.")
        note.setStyleSheet("color: #6b5f93; font-size: 11px;")
        col.addWidget(note)
        col.addStretch(1)
        return w

    def refresh_dnd(self):
        pet = self.pet
        if not hasattr(self, "dnd_list"):
            return
        now = datetime.now()
        cur = dnd_session_at(pet.dnd_games, now)
        nxt = dnd_next_game(pet.dnd_games, now)
        if cur:
            g, st, end = cur
            who = pet.call_name()
            self.dnd_status.setText(f"\U0001F3B2 {g['title']} is on now, until "
                                    f"{end.strftime('%I:%M %p').lstrip('0')}!"
                                    + (f" Digi calls you {who}." if who else ""))
        elif nxt:
            g, st = nxt
            day = ("today" if st.date() == now.date() else
                   "tomorrow" if st.date() == now.date() + timedelta(days=1) else st.strftime("%A"))
            self.dnd_status.setText(f"Next game: {g['title']}, {day} at {st.strftime('%I:%M %p').lstrip('0')}")
        else:
            self.dnd_status.setText("Add your game nights (D&D, Monster of the Week, Mothership...) "
                                    "and Digi will cheer you on! \U0001F3B2")
        self.dnd_list.clear()
        for g in pet.dnd_games:
            self.dnd_list.addItem(dnd_game_label(g))
        if not pet.dnd_games:
            it = QListWidgetItem("(no games yet!)")
            it.setFlags(Qt.NoItemFlags)
            self.dnd_list.addItem(it)
        for box, key in ((self.dnd_use_name, "use_name"), (self.dnd_dress, "dress")):
            box.blockSignals(True)
            box.setChecked(pet.dnd_opts.get(key, True))
            box.blockSignals(False)
        self.refresh_init()
        # notes: one page per game
        keep = self.notes_game.currentIndex()
        self.notes_game.blockSignals(True)
        self.notes_game.clear()
        for g in pet.dnd_games:
            self.notes_game.addItem(g["title"])
        if cur and cur[0] in pet.dnd_games and keep < 0:
            keep = pet.dnd_games.index(cur[0])
        self.notes_game.setCurrentIndex(min(max(keep, 0), len(pet.dnd_games) - 1)
                                        if pet.dnd_games else -1)
        self.notes_game.blockSignals(False)
        self.notes_game.setEnabled(bool(pet.dnd_games))
        self.notes_show()

    def refresh_init(self):
        ini = self.pet.dnd_init
        self.init_list.clear()
        manual = ini.get("manual", False)
        mine = self.pet.my_char_names()
        for i, e in enumerate(ini["order"]):
            mark = "\u25B6 " if i == ini["turn"] else "    "
            text = f"{i + 1}.  {e[0]}" if manual else init_label(e)
            if e[0].lower() in mine:
                text += "  \u2B50 you"
            it = QListWidgetItem(mark + text)
            if i == ini["turn"]:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            self.init_list.addItem(it)
        for k, b in self.init_mode_buttons.items():
            b.setChecked(k == ("manual" if manual else "roll"))
        self.init_roll_row.setVisible(not manual)
        self.init_d20_btn.setVisible(not manual)
        me = self.pet.my_char_name()
        self.init_me_btn.setVisible(bool(me))
        self.init_me_btn.setText(f"Add me ({me})" if me else "Add me")
        if not ini["order"]:
            it = QListWidgetItem("(add everyone in the order the GM calls them)" if manual
                                 else "(roll for initiative!)")
            it.setFlags(Qt.NoItemFlags)
            self.init_list.addItem(it)
            self.init_round.setText("Add each name in turn order. \u25B2 \u25BC move someone."
                                    if manual else "Add everyone with their roll; Digi keeps them in order.")
        else:
            self.init_round.setText(f"Round {ini['round']} \u00b7 {self.pet.dnd_turn_name()}'s turn")

    def dnd_opt(self, key, value):
        self.pet.dnd_opts[key] = bool(value)
        self.pet.dnd_changed()
        self.refresh_dnd()

    def dnd_add(self):
        dlg = DndGameEdit(self)
        if dlg.exec():
            g = dlg.result_item()
            self.pet.dnd_games.append(g)
            self.pet.dnd_changed()
            if not g["days"]:
                self.pet.say("Saved! Tick its game days so I know when to cheer you on~", 3500)
            elif g["role"] == "dm":
                self.pet.say(f"You're running {g['title']}! I'll bring my dragon book \U0001F4D6", 3500)
            else:
                self.pet.say(f"I'll bring my sword for {g['title']}! \u2694\ufe0f", 3500)
            self.refresh_dnd()

    def dnd_edit(self):
        i = self.dnd_list.currentRow()
        if i < 0 or i >= len(self.pet.dnd_games):
            return
        dlg = DndGameEdit(self, self.pet.dnd_games[i])
        if dlg.exec():
            self.pet.dnd_games[i] = dlg.result_item()
            self.pet.dnd_changed()
            self.refresh_dnd()

    def dnd_delete(self):
        i = self.dnd_list.currentRow()
        if i < 0 or i >= len(self.pet.dnd_games):
            return
        g = self.pet.dnd_games[i]
        extra = "\n\nIts session notes will be deleted too." if g["notes"].strip() else ""
        if QMessageBox.question(self, "Delete game",
                                "Delete this game?\n\n" + dnd_game_label(g) + extra) == QMessageBox.Yes:
            del self.pet.dnd_games[i]
            self.pet.dnd_changed()
            self.refresh_dnd()

    def init_add(self, roll=None):
        name = self.init_name.text().strip()
        if not name:
            self.init_name.setFocus()
            return
        if roll is None:
            roll = self.init_roll.value()
        mod = self.init_mod.value()
        ini = self.pet.dnd_init
        o = ini["order"]
        cur = o[ini["turn"] % len(o)] if o else None
        if ini.get("manual"):
            o.append(init_entry(name, 0, 0))     # your own order: they go at the end
        else:
            o.append(init_entry(name, roll, mod))
            o.sort(key=lambda e: (-e[1], -e[2]))     # highest first; a tie goes to the bigger modifier
        if cur is not None:                              # keep the turn on whoever had it
            ini["turn"] = next(i for i, e in enumerate(o) if e is cur)
        self.init_name.clear()
        self.init_roll.setValue(10)
        self.init_mod.setValue(0)
        self.pet.save_custom()
        self.pet.dnd_views_refresh()

    def init_set_mode(self, mode):
        ini = self.pet.dnd_init
        ini["manual"] = mode == "manual"
        if not ini["manual"] and ini["order"]:          # back to rolls: sort by them again
            cur = ini["order"][ini["turn"] % len(ini["order"])]
            ini["order"].sort(key=lambda e: (-e[1], -e[2]))
            ini["turn"] = next(i for i, e in enumerate(ini["order"]) if e is cur)
        self.pet.save_custom()
        self.pet.dnd_views_refresh()

    def init_add_me(self):
        me = self.pet.my_char_name()
        if me:
            self.init_name.setText(me)
            self.init_add()

    def init_move(self, step):
        i = self.init_list.currentRow()
        ini = self.pet.dnd_init
        o = ini["order"]
        j = i + step
        if i < 0 or i >= len(o) or not 0 <= j < len(o):
            return
        cur = o[ini["turn"] % len(o)]
        o[i], o[j] = o[j], o[i]
        ini["turn"] = next(k for k, e in enumerate(o) if e is cur)    # the turn stays with that person
        self.pet.save_custom()
        self.pet.dnd_views_refresh()
        self.init_list.setCurrentRow(j)

    def init_d20(self):
        name = self.init_name.text().strip()
        if not name:
            self.pet.say("Who am I rolling for? Type a name first~", 2500)
            self.init_name.setFocus()
            return
        r = random.randint(1, 20)
        mod = self.init_mod.value()
        total = f" {'+' if mod >= 0 else '-'} {abs(mod)} = {r + mod}" if mod else ""
        self.pet.say(f"{name} rolled a {r}{total}!" + (" \u2728 Natural 20!" if r == 20 else
                                                       " Oof, a 1~" if r == 1 else ""), 3000)
        self.init_add(r)

    def init_next(self):
        self.pet.dnd_next_turn()

    def init_remove(self):
        i = self.init_list.currentRow()
        ini = self.pet.dnd_init
        if i < 0 or i >= len(ini["order"]):
            return
        del ini["order"][i]
        if i < ini["turn"]:
            ini["turn"] -= 1
        if ini["turn"] >= len(ini["order"]):
            ini["turn"] = 0
        self.pet.save_custom()
        self.pet.dnd_views_refresh()

    def init_clear(self):
        if not self.pet.dnd_init["order"]:
            return
        if QMessageBox.question(self, "Clear initiative",
                                "Clear everyone from initiative? (Combat's over!)") == QMessageBox.Yes:
            self.pet.dnd_init = {"order": [], "turn": 0, "round": 1,
                                 "manual": self.pet.dnd_init.get("manual", False)}
            self.pet.save_custom()
            self.pet.dnd_views_refresh()

    def notes_show(self, *a):
        i = self.notes_game.currentIndex()
        games = self.pet.dnd_games
        self.notes_box.blockSignals(True)
        if 0 <= i < len(games):
            self.notes_box.setEnabled(True)
            if self.notes_box.toPlainText() != games[i]["notes"]:
                self.notes_box.setPlainText(games[i]["notes"])
        else:
            self.notes_box.setPlainText("")
            self.notes_box.setEnabled(False)
        self.notes_box.blockSignals(False)
        self.notes_box.setPlaceholderText("NPC names, loot, what happened last time..." if games
                                          else "Add a game first, then your notes go here~")

    def notes_export(self, everything):
        i = self.notes_game.currentIndex()
        if not everything and not (0 <= i < len(self.pet.dnd_games)):
            return
        self.pet.export_dnd_notes(self, None if everything else i)

    def notes_changed(self):
        i = self.notes_game.currentIndex()
        if 0 <= i < len(self.pet.dnd_games):
            self.pet.dnd_notes_set(i, self.notes_box.toPlainText(), self)

    def show_page(self, i):
        if not self.in_room:
            if hasattr(self, "tabs"):
                self.tabs.setCurrentIndex(i)
            return
        self.pages.setCurrentIndex(i)
        self.phone_title.setText(("Customize Digi", "About you", "Meditation", "My lists", "Game night")[i])
        for j, b in enumerate(self.dock_buttons):
            b.setChecked(i == j)
        if i == 3:
            self.refresh_lists()
        if i == 4:
            self.refresh_dnd()

    def hrow(self):
        return FlowLayout() if self.in_room else QHBoxLayout()

    def gridl(self):
        return FlowLayout() if self.in_room else QGridLayout()

    def room_k(self):
        return self.width() / ROOM_SIZE[0]

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self.in_room:
            return
        k = self.room_k()
        x, y, w, h = ROOM_SCREEN
        pw_, ph_ = int(w * k), int(h * k)
        if not ROOM_TILT:
            self.phone.setGeometry(int(x * k), int(y * k), pw_, ph_)
        else:
            self.place_tilted_phone(x, y, k, pw_, ph_)
        self.place_digi(k)

    def place_tilted_phone(self, x, y, k, pw_, ph_):
        pad = int(ph_ * math.sin(math.radians(abs(ROOM_TILT)))) + 4    # room for the turned corners
        self.phone.resize(pw_, ph_)
        self.phone_proxy.setTransformOriginPoint(pw_ / 2, ph_ / 2)
        self.phone_proxy.setRotation(ROOM_TILT)
        self.phone_proxy.setPos(pad, pad)
        self.phone_scene.setSceneRect(0, 0, pw_ + 2 * pad, ph_ + 2 * pad)
        self.phone_view.setSceneRect(0, 0, pw_ + 2 * pad, ph_ + 2 * pad)
        self.phone_view.setGeometry(int(x * k) - pad, int(y * k) - pad, pw_ + 2 * pad, ph_ + 2 * pad)

    def place_digi(self, k):
        cx, feet, tall = ROOM_DIGI
        ph = int(tall * k)
        pw = int(ph * 220 / 260)
        self.preview.setGeometry(int(cx * k - pw / 2), int(feet * k - ph), pw, ph)
        self.update_preview()
        QTimer.singleShot(0, self.fit_pages)

    def fit_pages(self):
        # wrapped button rows: tell each page how tall it really is at the phone's width
        for i in range(self.pages.count()):
            sc = self.pages.widget(i)
            w = sc.widget()
            lay = w.layout() if w else None
            if lay is not None and lay.hasHeightForWidth():
                vw = sc.viewport().width() - (0 if sc.verticalScrollBar().isVisible() else sc.verticalScrollBar().sizeHint().width())
                w.setMinimumHeight(lay.heightForWidth(max(80, vw)))

    def update_preview(self):
        k = getattr(self, "anim_k", 0)
        if self.in_room and self.preview.width() > 0:
            pm = self.pet.preview_pixmap(k, self.preview.width(), self.preview.height())
        else:
            pm = self.pet.preview_pixmap(k)
        self.preview.setPixmap(pm)

    def anim_step(self):
        # live Digi: she breathes / idles and blinks while you dress her up
        self.anim_k = getattr(self, "anim_k", 0) + 1
        try:
            self.update_preview()
            self.update_listen_button()
            if self.in_room:
                self.room_bubble.follow()
        except Exception as ex:
            self.anim.stop()
            print("preview:", ex, file=sys.stderr, flush=True)

    def showEvent(self, e):
        super().showEvent(e)
        self.anim.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.anim.stop()
        self.pet.preview_until = 0             # closing Customize stops a sample

    def paintEvent(self, e):
        if self.in_room:
            p = QPainter(self)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawPixmap(self.rect(), self.room)
            p.end()
        else:
            super().paintEvent(e)

    # ---------- the Meditation tab ----------
    def build_meditation(self):
        pet = self.pet
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(2, 2, 6, 2)
        col.addWidget(self.heading("Daily meditation \U0001F9D8"))
        row = self.hrow()
        self.med_on = QCheckBox("Invite me every day at")
        row.addWidget(self.med_on)
        self.med_at = QTimeEdit(QTime.fromString(pet.med_time or "12:00", "HH:mm"))
        self.med_at.setDisplayFormat("h:mm AP")
        self.med_at.setStyleSheet(self.BOX_STYLE)
        row.addWidget(self.med_at)
        row.addStretch(1)
        col.addLayout(row)
        self.med_on.setChecked(bool(pet.med_time))
        self.med_at.setEnabled(bool(pet.med_time))
        self.med_on.toggled.connect(lambda *a: self.pick_med_time())
        self.med_at.timeChanged.connect(lambda *a: self.pick_med_time())

        col.addWidget(self.heading("Background sound"))
        lab = QLabel("Plays softly only while you meditate. Pick one, then press Listen to hear a sample.")
        lab.setWordWrap(True)
        col.addWidget(lab)
        row = self.hrow()
        self.sound_buttons = {}
        self.sound_group = QButtonGroup(self)        # only one sound can be picked
        self.sound_group.setExclusive(True)
        for key, label in MED_SOUNDS:
            b = self.option(label)
            self.sound_group.addButton(b)
            b.clicked.connect(lambda *a, k=key: self.pick_med_sound(k))
            self.sound_buttons[key] = b
            row.addWidget(b)
        col.addLayout(row)
        row = self.hrow()
        self.listen_btn = QPushButton("\u25B6 Listen (5 sec)")
        self.listen_btn.setProperty("class", "opt")
        self.listen_btn.clicked.connect(lambda *a: self.listen())
        row.addWidget(self.listen_btn)
        col.addLayout(row)
        row = self.hrow()
        row.addWidget(QLabel("Volume"))
        self.med_vol = QSlider(Qt.Horizontal)
        self.med_vol.setRange(0, 100)
        self.med_vol.setValue(int(pet.med_volume * 100))
        self.med_vol.setMinimumWidth(120)
        self.med_vol.valueChanged.connect(lambda v: self.pick_med_volume(v))
        row.addWidget(self.med_vol)
        col.addLayout(row)

        col.addWidget(self.heading("Beginning chime"))
        lab = QLabel("Rings when a meditation starts. Tap one to hear it.")
        lab.setWordWrap(True)
        col.addWidget(lab)
        row = self.hrow()
        self.chime_buttons = {}
        self.chime_group = QButtonGroup(self)
        self.chime_group.setExclusive(True)
        for key, label in MED_CHIMES:
            b = self.option(label)
            self.chime_group.addButton(b)
            b.clicked.connect(lambda *a, k=key: self.pick_med_chime(k))
            self.chime_buttons[key] = b
            row.addWidget(b)
        col.addLayout(row)

        col.addWidget(self.heading("Breathing guide"))
        row = self.hrow()
        self.guide_buttons = {}
        self.guide_group = QButtonGroup(self)
        self.guide_group.setExclusive(True)
        for key, label in ((True, "Words + glow"), (False, "Just the glow")):
            b = self.option(label)
            self.guide_group.addButton(b)
            b.clicked.connect(lambda *a, k=key: self.pick_med_guide(k))
            self.guide_buttons[key] = b
            row.addWidget(b)
        col.addLayout(row)

        col.addWidget(self.heading("Meditate now"))
        row = self.hrow()
        for m in MED_CHOICES:
            b = self.option(f"{m} min")
            b.setCheckable(False)
            b.clicked.connect(lambda *a, m=m: self.start_med_now(m))
            row.addWidget(b)
        col.addLayout(row)
        self.med_stats = QLabel("")
        self.med_stats.setWordWrap(True)
        col.addWidget(self.med_stats)
        col.addStretch(1)
        return w

    def pick_med_sound(self, key):
        self.pet.med_sound = key
        self.pet.save_custom()
        if time.time() < self.pet.preview_until:      # a sample was playing: switch it to this one
            self.pet.preview_until = 0
            if key != "none":
                self.pet.listen_sample(key)
        self.refresh()

    def pick_med_chime(self, key):
        self.pet.med_chime = key
        self.pet.save_custom()
        self.pet.play_chime(key)
        self.refresh()

    def listen(self):
        key = self.pet.med_sound
        if key == "none":
            self.pet.say("Pick a sound first, then press Listen~", 2500)
            return
        self.pet.listen_sample(key)
        self.update_listen_button()

    def update_listen_button(self):
        if not hasattr(self, "listen_btn"):
            return
        playing = time.time() < self.pet.preview_until
        txt = "\u25A0 Stop" if playing else "\u25B6 Listen (5 sec)"
        if self.listen_btn.text() != txt:
            self.listen_btn.setText(txt)

    def pick_med_volume(self, v):
        self.pet.med_volume = v / 100
        self.pet.save_custom()

    def pick_med_guide(self, k):
        self.pet.set_med_guide(k)
        self.refresh()

    def start_med_now(self, m):
        self.accept()
        self.pet.start_meditation(m)

    # ---------- the Personal settings tab ----------
    BOX_STYLE = ("QLineEdit, QTimeEdit { padding: 5px 8px; border-radius: 8px; border: 1px solid #c9bfe3; "
                 "background: white; color: #3a3159; }")

    def build_personal(self):
        w = QWidget()
        col = QVBoxLayout(w)
        pet = self.pet

        col.addWidget(self.heading("What should I call you?"))
        self.name_box = QLineEdit(pet.nickname)
        self.name_box.setPlaceholderText("Your name or nickname (leave empty for none)")
        self.name_box.setMaxLength(24)
        self.name_box.setStyleSheet(self.BOX_STYLE)
        self.name_box.editingFinished.connect(self.pick_name)
        col.addWidget(self.name_box)

        col.addWidget(self.heading("Where do you live? (for the weather)"))
        row = self.hrow()
        self.city_box = QLineEdit()
        self.city_box.setPlaceholderText("Type your city, then press Find")
        self.city_box.setStyleSheet(self.BOX_STYLE)
        self.city_box.returnPressed.connect(self.find_city)
        row.addWidget(self.city_box)
        find = self.option("Find")
        find.setCheckable(False)
        find.clicked.connect(self.find_city)
        row.addWidget(find)
        col.addLayout(row)
        self.city_results = QListWidget()
        self.city_results.setMaximumHeight(110)
        self.city_results.setStyleSheet("QListWidget { background: white; color: #3a3159; border-radius: 8px; "
                                        "border: 1px solid #c9bfe3; }")
        self.city_results.itemClicked.connect(self.pick_city)
        self.city_results.hide()
        col.addWidget(self.city_results)
        row = self.hrow()
        self.place_label = QLabel()
        row.addWidget(self.place_label)
        row.addStretch(1)
        self.unit_buttons = {}
        for key, label in (("F", "\u00b0F"), ("C", "\u00b0C")):
            b = self.option(label)
            b.clicked.connect(lambda *a, k=key: self.pick_units(k))
            self.unit_buttons[key] = b
            row.addWidget(b)
        col.addLayout(row)

        col.addWidget(self.heading("Your schedule"))
        row = self.hrow()
        lab = QLabel("Meals, water breaks, stretches... she reminds you every day.")
        lab.setWordWrap(True)
        row.addWidget(lab, 1)
        edit = self.option("Edit my reminders...")
        edit.setCheckable(False)
        edit.clicked.connect(lambda *a: self.show_page(3))             # the Lists tab
        row.addWidget(edit)
        col.addLayout(row)

        col.addWidget(self.heading("Birthdays \U0001F382"))
        row = self.hrow()
        row.addWidget(QLabel("Your birthday:"))
        self.my_month = QComboBox()
        self.my_month.addItems(["(not set)"] + MONTHS)
        self.my_day = QSpinBox()
        self.my_day.setRange(1, 31)
        for wdg in (self.my_month, self.my_day):
            wdg.setStyleSheet("QComboBox, QSpinBox { padding: 3px 6px; border-radius: 6px; "
                              "border: 1px solid #c9bfe3; background: white; color: #3a3159; }")
        if pet.my_birthday:
            self.my_month.setCurrentIndex(pet.my_birthday["month"])
            self.my_day.setValue(pet.my_birthday["day"])
        self.my_day.setEnabled(pet.my_birthday is not None)
        self.my_month.currentIndexChanged.connect(lambda *a: self.pick_my_birthday())
        self.my_day.valueChanged.connect(lambda *a: self.pick_my_birthday())
        row.addWidget(self.my_month)
        row.addWidget(self.my_day)
        row.addStretch(1)
        friends = self.option("Other birthdays...")
        friends.setCheckable(False)
        friends.clicked.connect(lambda *a: self.show_page(3))
        row.addWidget(friends)
        col.addLayout(row)

        col.addWidget(self.heading("Bedtime (she naps too)"))
        row = self.hrow()
        self.sleep_on = QCheckBox("Nap at night")
        row.addWidget(self.sleep_on)
        sh = pet.sleep_hours_set or ["00:30", "08:30"]
        self.sleep_from = QTimeEdit(QTime.fromString(sh[0], "HH:mm"))
        self.sleep_to = QTimeEdit(QTime.fromString(sh[1], "HH:mm"))
        for t in (self.sleep_from, self.sleep_to):
            t.setDisplayFormat("h:mm AP")
            t.setStyleSheet(self.BOX_STYLE)
        row.addWidget(QLabel("from"))
        row.addWidget(self.sleep_from)
        row.addWidget(QLabel("to"))
        row.addWidget(self.sleep_to)
        row.addStretch(1)
        col.addLayout(row)
        self.sleep_on.setChecked(bool(pet.sleep_hours_set))
        self.sleep_on.toggled.connect(lambda *a: self.pick_sleep())
        self.sleep_from.timeChanged.connect(lambda *a: self.pick_sleep())
        self.sleep_to.timeChanged.connect(lambda *a: self.pick_sleep())

        lab = QLabel("\U0001F3B2 Game nights have their own tab now!")
        lab.setStyleSheet("color: #6b5f93; font-size: 11px;")
        col.addWidget(lab)
        col.addStretch(1)
        return w

    def find_city(self):
        q = self.city_box.text().strip()
        if not q:
            return
        import urllib.request
        import urllib.parse
        url = ("https://geocoding-api.open-meteo.com/v1/search?count=6&language=en&format=json&name="
               + urllib.parse.quote(q))
        self.city_results.clear()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            try:
                with urllib.request.urlopen(url, timeout=10) as r:
                    data = json.loads(r.read().decode())
            except Exception:
                with urllib.request.urlopen(url.replace("https://", "http://"), timeout=10) as r:
                    data = json.loads(r.read().decode())
            results = data.get("results") or []
        except Exception:
            results = None
        finally:
            QApplication.restoreOverrideCursor()
        if results is None:
            self.city_results.addItem("Hmm, I couldn't look that up. Are you online?")
        elif not results:
            self.city_results.addItem("No city by that name~ try another spelling?")
        for c in results or []:
            label = ", ".join(x for x in (c.get("name"), c.get("admin1"), c.get("country")) if x)
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, {"name": label, "lat": c["latitude"], "lon": c["longitude"]})
            self.city_results.addItem(it)
        self.city_results.show()

    def pick_city(self, item):
        pl = item.data(Qt.UserRole)
        if not pl:
            return
        self.pet.place = pl
        self.pet.weather = None
        self.pet.save_custom()
        self.city_results.hide()
        self.city_box.clear()
        self.pet.say(f"Got it! I'll watch the weather in {pl['name'].split(',')[0]}~", 3000)
        self.refresh()

    def pick_units(self, k):
        self.pet.units = k
        self.pet.weather = None
        self.pet.save_custom()
        self.refresh()

    def pick_med_time(self):
        on = self.med_on.isChecked()
        self.med_at.setEnabled(on)
        self.pet.set_med_time(self.med_at.time().toString("HH:mm") if on else None)

    def pick_sleep(self):
        global SLEEP_HOURS
        if self.sleep_on.isChecked():
            self.pet.sleep_hours_set = [self.sleep_from.time().toString("HH:mm"),
                                        self.sleep_to.time().toString("HH:mm")]
        else:
            self.pet.sleep_hours_set = None
        SLEEP_HOURS = tuple(self.pet.sleep_hours_set) if self.pet.sleep_hours_set else None
        self.sleep_from.setEnabled(self.sleep_on.isChecked())
        self.sleep_to.setEnabled(self.sleep_on.isChecked())
        self.pet.save_custom()

    def heading(self, text):
        lab = QLabel(text)
        lab.setObjectName("h")
        lab.setWordWrap(True)           # long ones wrap on the narrow phone screen
        return lab

    def option(self, text):
        b = QPushButton(text)
        b.setProperty("class", "opt")
        b.setCheckable(True)
        return b

    def refresh(self):
        pet = self.pet
        self.refresh_lists()
        self.refresh_dnd()
        for k, b in self.style_hair_buttons.items():
            b.setChecked(k == pet.hairstyle)
        for k, b in self.bubble_buttons.items():
            b.setChecked(k == pet.bubble_mode)
        for k, b in getattr(self, "sound_buttons", {}).items():
            b.setChecked(k == pet.med_sound)
        for k, b in getattr(self, "chime_buttons", {}).items():
            b.setChecked(k == pet.med_chime)
        for k, b in getattr(self, "guide_buttons", {}).items():
            b.setChecked(k == pet.med_guide)
        if hasattr(self, "med_stats"):
            if pet.med_days:
                n = pet.med_streak()
                days = len(set(pet.med_days))
                self.med_stats.setText(("\U0001F33F %d days in a row \u2022 " % n if n > 1 else "\U0001F33F ")
                                       + f"{days} day{'s' if days != 1 else ''}, {pet.med_total} minutes in all")
            else:
                self.med_stats.setText("\U0001F33F No meditations yet. Try 5 minutes!")
        for k, b in self.shape_buttons.items():
            b.setChecked(k == pet.bubble_shape)
        for k, b in self.spot_buttons.items():
            b.setChecked(k == pet.bubble_pos)
        for k, b in self.outline_buttons.items():
            b.setChecked(k == pet.outline)
        for k, b in self.unit_buttons.items():
            b.setChecked(k == pet.units)
        self.place_label.setText("Weather for: " + (pet.place["name"] if pet.place else "(no city yet)"))
        self.sleep_from.setEnabled(bool(pet.sleep_hours_set))
        self.sleep_to.setEnabled(bool(pet.sleep_hours_set))
        for k, b in self.textsize_buttons.items():
            b.setChecked(k == pet.text_size)
        for k, b in self.bottom_buttons.items():
            b.setChecked(k == pet.bottom)
        for k, b in self.swatches.items():
            b.setChecked((k or None) == (pet.hair_color.upper() if pet.hair_color else None))
        for k, b in self.outfit_buttons.items():
            b.setChecked(k == pet.acc_mode)
        for k, b in self.style_buttons.items():
            b.setChecked(k == pet.outfit_style)
        self.update_preview()

    def pick_hairstyle(self, k):
        self.pet.set_hairstyle(k)
        self.refresh()

    def pick_bubble(self, k):
        self.pet.bubble_mode = k
        self.pet.save_custom()
        self.pet.say("Like my new bubble?" if k == "dark" else "Back to a bright bubble~", 2500)
        self.refresh()

    def pick_my_birthday(self):
        m = self.my_month.currentIndex()
        self.my_day.setEnabled(m > 0)
        new = {"month": m, "day": self.my_day.value()} if m > 0 else None
        if new == self.pet.my_birthday:
            return
        self.pet.my_birthday = new
        self.pet.save_custom()

    def pick_bubble_shape(self, k):
        self.pet.bubble_shape = k
        self.pet.save_custom()
        self.pet.say("Hmm... I'm thinking~" if k == "thought" else "Back to talking!", 2500)
        self.refresh()

    def pick_bubble_pos(self, k):
        self.pet.bubble_pos = k
        self.pet.save_custom()
        self.pet.say("Over here now! Is this better?" if k == "side" else "Up here~", 2500)
        self.refresh()

    def pick_name(self):
        name = self.name_box.text().strip()
        if name == self.pet.nickname:
            return
        self.pet.nickname = name
        self.pet.save_custom()
        self.pet.say(f"Okay, {name}! \u2665" if name else "Okay~ no names!", 2500)
        self.pet.happy = 20

    def pick_outline(self, k):
        self.pet.outline = k
        self.pet.save_custom()
        self.pet.update()
        self.pet.say("Glow on, so I don't get lost in dark mode! \u2728" if k == "glow"
                     else "No glow~ I'll try not to get lost!", 2500)
        self.refresh()

    def pick_textsize(self, k):
        self.pet.text_size = k
        self.pet.save_custom()
        self.pet.say({"small": "Is this easier?", "medium": "Just right~",
                      "large": "CAN YOU HEAR ME NOW? Hehe"}[k], 2500)
        self.refresh()

    def pick_bottom(self, k):
        self.pet.set_bottom(k)
        self.refresh()

    def pick_hair(self, hx):
        self.pet.set_hair(hx)
        self.refresh()

    def pick_any(self):
        start = QColor(self.pet.hair_color or "#615E9B")
        c = QColorDialog.getColor(start, self, "Pick Digi's hair color")
        if c.isValid():
            self.pet.set_hair(c.name().upper())
        self.refresh()

    def pick_outfit(self, k):
        self.pet.set_outfit(k)
        self.pet.save_custom()
        self.refresh()

    def pick_style(self, k):
        self.pet.set_outfit_style(k)
        self.pet.save_custom()
        self.refresh()


class ReminderEdit(QDialog):
    """Add or change one reminder."""

    def __init__(self, parent, item=None):
        super().__init__(parent)
        self.setWindowTitle("Reminder")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("What time?"))
        self.time = QTimeEdit()
        self.time.setDisplayFormat("h:mm AP")
        lay.addWidget(self.time)
        lay.addWidget(QLabel("What should she say?"))
        self.text = QLineEdit()
        self.text.setPlaceholderText("Water break! Sip sip!")
        lay.addWidget(self.text)
        lay.addWidget(QLabel("Which days?"))
        row = QHBoxLayout()
        self.days = {}
        for d in DAY_ORDER:
            cb = QCheckBox(d)
            cb.setChecked(True)
            self.days[d] = cb
            row.addWidget(cb)
        lay.addLayout(row)
        btns = QHBoxLayout()
        cancel = QPushButton("Cancel")
        ok = QPushButton("Save")
        ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)
        if item:
            h, m = (int(x) for x in item[0].split(":"))
            self.time.setTime(QTime(h, m))
            self.text.setText(item[1])
            days = item[2] if len(item) > 2 and item[2] else DAY_ORDER
            for d, cb in self.days.items():
                cb.setChecked(d in days)
        else:
            self.time.setTime(QTime(12, 0))

    def result_item(self):
        when = self.time.time().toString("HH:mm")
        text = self.text.text().strip() or "Reminder!"
        days = [d for d in DAY_ORDER if self.days[d].isChecked()]
        if not days or len(days) == 7:
            return (when, text)
        return (when, text, days)


class ModSpin(QSpinBox):
    """A spin box that shows a modifier with its sign: +2, 0, -1."""

    def textFromValue(self, v):
        return f"+{v}" if v > 0 else str(v)


def init_entry(name, roll, mod):
    """One line of initiative: [name, total, mod, roll]."""
    return [name[:24], roll + mod, mod, roll]


def init_label(e):
    total = e[1]
    mod, roll = (e[2], e[3]) if len(e) >= 4 else (0, e[1])
    how = f"   ({roll} {'+' if mod >= 0 else '-'} {abs(mod)})" if mod else ""
    return f"{total:>2}   {e[0]}{how}"


class DndNotesWindow(QWidget):
    """A small notes window you can keep open beside your game (big, easy-to-read text),
    with whose turn it is at the bottom."""

    def __init__(self, pet):
        super().__init__(None)
        self.pet = pet
        self.setWindowTitle("Game night notes")
        self.setWindowFlag(Qt.Window, True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(pet.dnd_opts.get("notes_pin", True)))
        self.setStyleSheet("""
            QWidget { background: #f6f3fb; color: #3a3159; }
            QPlainTextEdit { background: white; border: 1px solid #ddd5ef; border-radius: 8px; padding: 4px; }
            QComboBox { background: white; border: 1px solid #c9bfe3; border-radius: 6px; padding: 2px 6px; }
            QPushButton { padding: 3px 9px; border-radius: 8px; border: 1px solid #c9bfe3; background: white; }
            QPushButton:hover { background: #efeaf9; }
            QPushButton:checked { background: #a99be0; color: white; border-color: #6b5f93; }
            QLabel#turn { font-weight: bold; color: #4b3f7a; }
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        top = QHBoxLayout()
        self.game = QComboBox()
        self.game.currentIndexChanged.connect(self.load)
        top.addWidget(self.game, 1)
        for label, step, tip in (("A\u2212", -1, "Smaller text"), ("A+", 1, "Bigger text")):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(lambda *a, st=step: self.font_step(st))
            top.addWidget(b)
        save = QPushButton("Export")
        save.setToolTip("Save these notes to a file")
        save.clicked.connect(lambda *a: self.pet.export_dnd_notes(self, self.game.currentIndex())
                             if self.game.currentIndex() >= 0 else None)
        top.addWidget(save)
        self.pin = QPushButton("\U0001F4CC")
        self.pin.setToolTip("Keep this window on top of everything")
        self.pin.setCheckable(True)
        self.pin.setChecked(bool(pet.dnd_opts.get("notes_pin", True)))
        self.pin.toggled.connect(self.set_pin)
        top.addWidget(self.pin)
        lay.addLayout(top)
        self.box = QPlainTextEdit()
        self.box.setPlaceholderText("NPC names, loot, clues, what happened last time...")
        self.box.textChanged.connect(self.changed)
        lay.addWidget(self.box, 1)
        bottom = QHBoxLayout()
        self.turn = QLabel()
        self.turn.setObjectName("turn")
        bottom.addWidget(self.turn, 1)
        self.next_btn = QPushButton("Next turn \u25B6")
        self.next_btn.clicked.connect(self.next_turn)
        bottom.addWidget(self.next_btn)
        lay.addLayout(bottom)
        self.apply_font()
        geo = pet.dnd_opts.get("notes_geo")
        if isinstance(geo, list) and len(geo) == 4:
            self.setGeometry(*[int(v) for v in geo])
            scr = QGuiApplication.screenAt(self.geometry().center())
            if scr is None:                       # that screen is gone: start somewhere visible
                self.resize(int(geo[2]), int(geo[3]))
                self.move(120, 120)
        else:
            self.resize(380, 460)

    def refresh(self, index=None):
        games = self.pet.dnd_games
        keep = self.game.currentIndex() if index is None else index
        self.game.blockSignals(True)
        self.game.clear()
        for g in games:
            self.game.addItem(g["title"])
        self.game.setCurrentIndex(min(max(keep, 0), len(games) - 1) if games else -1)
        self.game.blockSignals(False)
        self.load()
        self.refresh_init()

    def load(self, *a):
        i = self.game.currentIndex()
        games = self.pet.dnd_games
        text = games[i]["notes"] if 0 <= i < len(games) else ""
        if self.box.toPlainText() != text:
            self.box.blockSignals(True)
            self.box.setPlainText(text)
            self.box.moveCursor(QTextCursor.End)
            self.box.blockSignals(False)
        self.box.setEnabled(0 <= i < len(games))

    def changed(self):
        i = self.game.currentIndex()
        if 0 <= i < len(self.pet.dnd_games):
            self.pet.dnd_notes_set(i, self.box.toPlainText(), self)

    def refresh_init(self):
        who = self.pet.dnd_turn_name()
        if who:
            self.turn.setText(f"\u2694\ufe0f Round {self.pet.dnd_init['round']} \u00b7 {who}'s turn")
        else:
            self.turn.setText("No initiative yet (add it in Customize \u2192 Game night)")
        self.next_btn.setEnabled(bool(who))

    def next_turn(self):
        self.pet.dnd_next_turn()

    def apply_font(self):
        size = int(self.pet.dnd_opts.get("notes_font", 15))
        f = self.box.font()
        f.setPointSize(size)
        self.box.setFont(f)

    def font_step(self, step):
        self.pet.dnd_opts["notes_font"] = max(10, min(32, int(self.pet.dnd_opts.get("notes_font", 15)) + step * 2))
        self.apply_font()
        self.pet.save_custom()

    def set_pin(self, on):
        self.pet.dnd_opts["notes_pin"] = bool(on)
        geo = self.geometry()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(on))
        self.setGeometry(geo)
        self.show()                               # changing that flag hides the window: bring it back
        self.pet.save_custom()

    def remember_place(self):
        g = self.geometry()
        self.pet.dnd_opts["notes_geo"] = [g.x(), g.y(), g.width(), g.height()]
        self.pet.save_custom()

    def moveEvent(self, e):
        super().moveEvent(e)
        self.pet.dnd_place_later()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.pet.dnd_place_later()

    def closeEvent(self, e):
        self.remember_place()
        super().closeEvent(e)


class DndGameEdit(QDialog):
    """Add or change one game night: its name, days, time, and whether you're the GM or a player."""

    def __init__(self, parent, game=None):
        super().__init__(parent)
        self.setWindowTitle("Game night")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        game = game or {"title": "", "role": "player", "char": "", "days": [], "start": "19:00",
                        "hours": 4, "notes": ""}
        self.notes = game.get("notes", "")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Name of the game"))
        self.title = QLineEdit(game["title"])
        self.title.setPlaceholderText("Curse of Strahd, Monster of the Week, Mothership...")
        self.title.setMaxLength(40)
        lay.addWidget(self.title)
        lay.addWidget(QLabel("You are the..."))
        rrow = QHBoxLayout()
        self.dm = QRadioButton("GM / DM / Keeper \U0001F4D6 (Digi brings her dragon book)")
        self.player = QRadioButton("Player \u2694\ufe0f (Digi brings her sword)")
        (self.dm if game["role"] == "dm" else self.player).setChecked(True)
        rl = QVBoxLayout()
        rl.addWidget(self.dm)
        rl.addWidget(self.player)
        rrow.addLayout(rl)
        lay.addLayout(rrow)
        self.char_label = QLabel()
        lay.addWidget(self.char_label)
        self.char = QLineEdit(game["char"])
        self.char.setMaxLength(24)
        lay.addWidget(self.char)
        self.dm.toggled.connect(self.role_changed)
        self.role_changed()
        lay.addWidget(QLabel("Game days (tick every day you play)"))
        drow = QHBoxLayout()
        self.days = {}
        for d in DAY_ORDER:
            c = QCheckBox(d)
            c.setChecked(d in game["days"])
            self.days[d] = c
            drow.addWidget(c)
        drow.addStretch(1)
        lay.addLayout(drow)
        trow = QHBoxLayout()
        trow.addWidget(QLabel("Starts at"))
        self.start = QTimeEdit(QTime.fromString(game["start"], "HH:mm"))
        self.start.setDisplayFormat("h:mm AP")
        trow.addWidget(self.start)
        trow.addWidget(QLabel("for"))
        self.hours = QSpinBox()
        self.hours.setRange(1, 12)
        self.hours.setValue(int(round(game["hours"])))
        trow.addWidget(self.hours)
        trow.addWidget(QLabel("hours"))
        trow.addStretch(1)
        lay.addLayout(trow)
        btns = QHBoxLayout()
        cancel = QPushButton("Cancel")
        ok = QPushButton("Save")
        ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def role_changed(self, *a):
        if self.dm.isChecked():
            self.char_label.setText("What should Digi call you at the table? (optional)")
            self.char.setPlaceholderText("Leave empty: Dungeon Master for D&D, Game Master for others")
        else:
            self.char_label.setText("Your character's name (Digi calls you this during the game)")
            self.char.setPlaceholderText("Rainy, Thorin, Lady Moonwhisper...")

    def result_item(self):
        return clean_dnd_game({"title": self.title.text().strip() or "Game night",
                               "role": "dm" if self.dm.isChecked() else "player",
                               "char": self.char.text().strip(),
                               "days": [d for d, c in self.days.items() if c.isChecked()],
                               "start": self.start.time().toString("HH:mm"),
                               "hours": self.hours.value(), "notes": self.notes})


class TriviaEdit(QDialog):
    """Add or change one of your own trivia questions."""

    def __init__(self, parent, item=None):
        super().__init__(parent)
        self.setWindowTitle("My trivia")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        item = item or {"q": "", "a": "", "wrong": []}
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Question"))
        self.q = QLineEdit(item["q"])
        self.q.setMaxLength(90)
        self.q.setPlaceholderText("What's the name of our party's tavern?")
        lay.addWidget(self.q)
        lay.addWidget(QLabel("Right answer (keep it short: it goes on a button)"))
        self.a = QLineEdit(item["a"])
        self.a.setMaxLength(24)
        lay.addWidget(self.a)
        lay.addWidget(QLabel("Wrong answers (at least one)"))
        self.wrong = []
        for i in range(3):
            w = QLineEdit(item["wrong"][i] if i < len(item["wrong"]) else "")
            w.setMaxLength(24)
            lay.addWidget(w)
            self.wrong.append(w)
        btns = QHBoxLayout()
        cancel = QPushButton("Cancel")
        ok = QPushButton("Save")
        ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.try_accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def try_accept(self):
        if self.result_item() is None:
            QMessageBox.information(self, "My trivia",
                                    "It needs a question, a right answer and at least one wrong answer.")
            return
        self.accept()

    def result_item(self):
        return clean_trivia({"q": self.q.text(), "a": self.a.text(), "wrong": [w.text() for w in self.wrong]})


class BirthdayEdit(QDialog):
    """Add or change one birthday."""

    def __init__(self, parent, item=None):
        super().__init__(parent)
        self.setWindowTitle("Birthday")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Whose birthday?"))
        self.name = QLineEdit()
        self.name.setPlaceholderText("Mom, Alex, Grandpa...")
        self.name.setMaxLength(40)
        lay.addWidget(self.name)
        lay.addWidget(QLabel("When?"))
        row = QHBoxLayout()
        self.month = QComboBox()
        self.month.addItems(MONTHS)
        self.day = QSpinBox()
        self.day.setRange(1, 31)
        row.addWidget(self.month)
        row.addWidget(self.day)
        row.addStretch(1)
        lay.addLayout(row)
        btns = QHBoxLayout()
        cancel = QPushButton("Cancel")
        ok = QPushButton("Save")
        ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)
        if item:
            self.name.setText(item["name"])
            self.month.setCurrentIndex(item["month"] - 1)
            self.day.setValue(item["day"])

    def result_item(self):
        return {"name": self.name.text().strip() or "Someone",
                "month": self.month.currentIndex() + 1, "day": self.day.value()}


class BirthdayManager(QDialog):
    """Birthdays she remembers for you (she reminds you a week before, the day before and on the day)."""

    def __init__(self, pet):
        super().__init__(None)
        self.pet = pet
        self.setWindowTitle("Birthdays")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.resize(420, 380)
        lay = QVBoxLayout(self)
        tip = QLabel("I'll remind you a week before, the day before, and on the day! \U0001F382")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self.edit())
        lay.addWidget(self.list)
        row = QHBoxLayout()
        for label, fn in (("Add", self.add), ("Edit", self.edit),
                          ("Delete", self.delete), ("Done", self.accept)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        self.refresh()

    def refresh(self):
        # soonest birthday first
        self.pet.birthdays.sort(key=lambda b: days_until_birthday(b["month"], b["day"]))
        self.list.clear()
        for b in self.pet.birthdays:
            n = days_until_birthday(b["month"], b["day"])
            when = "today!" if n == 0 else ("tomorrow" if n == 1 else f"in {n} days")
            self.list.addItem(QListWidgetItem(f"{birthday_label(b)}   ({when})"))

    def changed(self):
        self.pet.save_custom()
        self.refresh()

    def add(self):
        dlg = BirthdayEdit(self)
        if dlg.exec():
            b = dlg.result_item()
            self.pet.birthdays.append(b)
            self.changed()
            self.pet.say(f"Got it! I'll remember {b['name']}'s birthday \U0001F382", 3000)

    def edit(self):
        i = self.list.currentRow()
        if i < 0:
            return
        dlg = BirthdayEdit(self, self.pet.birthdays[i])
        if dlg.exec():
            self.pet.birthdays[i] = dlg.result_item()
            self.changed()

    def delete(self):
        i = self.list.currentRow()
        if i < 0:
            return
        b = self.pet.birthdays[i]
        ans = QMessageBox.question(self, "Delete birthday", "Forget this birthday?\n\n" + birthday_label(b))
        if ans == QMessageBox.Yes:
            del self.pet.birthdays[i]
            self.changed()


class ReminderManager(QDialog):
    """The list of all her reminders, with add / edit / delete."""

    def __init__(self, pet):
        super().__init__(None)
        self.pet = pet
        self.setWindowTitle("DigiPal reminders")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.resize(460, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Double-click a reminder to change it."))
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self.edit())
        lay.addWidget(self.list)
        row = QHBoxLayout()
        for label, fn in (("Add", self.add), ("Edit", self.edit),
                          ("Delete", self.delete), ("Done", self.accept)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        bd = QPushButton("Birthdays... \U0001F382")
        bd.clicked.connect(lambda *a: self.pet.open_birthdays())
        lay.addWidget(bd)
        self.refresh()

    def refresh(self):
        self.pet.reminders.sort(key=lambda r: r[0])
        self.list.clear()
        for r in self.pet.reminders:
            self.list.addItem(QListWidgetItem(reminder_label(r)))

    def changed(self):
        save_reminders(self.pet.reminders)
        self.refresh()

    def add(self):
        dlg = ReminderEdit(self)
        if dlg.exec():
            self.pet.reminders.append(dlg.result_item())
            self.changed()

    def edit(self):
        i = self.list.currentRow()
        if i < 0:
            return
        dlg = ReminderEdit(self, self.pet.reminders[i])
        if dlg.exec():
            self.pet.reminders[i] = dlg.result_item()
            self.changed()

    def delete(self):
        i = self.list.currentRow()
        if i < 0:
            return
        r = self.pet.reminders[i]
        ans = QMessageBox.question(self, "Delete reminder",
                                   "Delete this reminder?\n\n" + reminder_label(r))
        if ans == QMessageBox.Yes:
            del self.pet.reminders[i]
            self.changed()
LAUNCH_AGENT = os.path.expanduser(
    "~/Library/LaunchAgents/com.deskpet.companion.plist")
ART_NAMES = ["idle", "blink", "happy", "sleepy", "surprised"]

# things she says while you hold her up like a cat
HELD_LINES = ["...", "I live here now.", "Put me down~", "Just hanging out.",
              "Wheee... I guess.", "*dangles*", "This is fine."]

# windows that are not real app windows (she ignores these)
SKIP_OWNERS = {"Window Server", "Dock", "Control Center",
               "Notification Center", "Spotlight"}

# ---- music / video detection ----
PLAYER_APPS = ["Spotify", "Music"]
CHROMIUM_BROWSERS = ["Google Chrome", "Brave Browser", "Microsoft Edge", "Arc"]

PLAYER_SCRIPT = '''
tell application "APPNAME" to return player state as string
'''

JS_CHECK = ("(function(){var v=document.querySelector('video');"
            "return (v && !v.paused && !v.muted && v.volume>0 && v.currentTime>0)"
            " ? 'playing' : 'no';})()")

CHROMIUM_SCRIPT = '''
tell application "APPNAME"
    repeat with w in windows
        repeat with t in tabs of w
            set u to URL of t
            if u contains "youtube.com/watch" or u contains "youtube.com/shorts" or u contains "music.youtube.com" then
                set r to execute t javascript "JSCODE"
                if r is "playing" then return "playing"
            end if
        end repeat
    end repeat
end tell
return "no"
'''

SAFARI_SCRIPT = '''
tell application "Safari"
    repeat with w in windows
        repeat with t in tabs of w
            set u to URL of t
            if u contains "youtube.com/watch" or u contains "youtube.com/shorts" or u contains "music.youtube.com" then
                set r to do JavaScript "JSCODE" in t
                if r is "playing" then return "playing"
            end if
        end repeat
    end repeat
end tell
return "no"
'''


def is_running(app_name):
    try:
        r = subprocess.run(["pgrep", "-x", app_name],
                           capture_output=True, timeout=3)
        return r.returncode == 0
    except Exception:
        return False


def to_minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def minutes_label(m):
    if m == 1:
        return "1 minute"
    if m == 60:
        return "1 hour"
    return f"{m} minutes"


def in_sleep_hours():
    if not SLEEP_HOURS:
        return False
    now = datetime.now()
    cur = now.hour * 60 + now.minute
    s = to_minutes(SLEEP_HOURS[0])
    e = to_minutes(SLEEP_HOURS[1])
    if s < e:
        return s <= cur < e
    return cur >= s or cur < e


def autostart_enabled():
    if HELPER:
        return W is not None and W.autostart_enabled()
    return os.path.exists(LAUNCH_AGENT)


class LazyPix:
    """A list of frames that only loads each picture the first time it's shown
    (so switching outfits or hair doesn't freeze her while hundreds of files load)."""

    def __init__(self, paths, optional=False):
        self.paths = paths
        self.optional = optional
        self._c = {}

    def __len__(self):
        return len(self.paths)

    def __bool__(self):
        return bool(self.paths)

    def __getitem__(self, i):
        if i < 0:
            i += len(self.paths)
        if i not in self._c:
            p = self.paths[i]
            pm = None
            if not self.optional or os.path.exists(p):
                pm = QPixmap(p)
                if pm.isNull() and self.optional:
                    pm = None
            self._c[i] = pm
        return self._c[i]

    def __iter__(self):
        for i in range(len(self.paths)):
            yield self[i]


class BubbleWin(QWidget):
    """Her speech / thought bubble, in its own see-through window so it can sit above her head
    or beside her without covering her (and without making her own window bigger)."""
    PAD = 8           # room around the bubble for its outline
    TAIL = 22         # room for the tail / little thought circles

    def __init__(self, pet):
        super().__init__(None)
        self.pet = pet
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | TOOL_FLAG
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.key = None
        self.layout_ = None
        self.side = "above"           # where it actually is right now: above / right / left
        self.resize(10, 10)

    # ---- where it goes
    def follow(self):
        pet = self.pet
        text = pet.msg
        cw = getattr(pet, "custom_win", None)
        if cw is not None and cw.isVisible() and getattr(cw, "in_room", False):
            text = None                  # she talks inside her room while Customize is open
        if not text or not pet.isVisible() or getattr(pet, "hidden_for_shot", False):
            if self.isVisible():
                self.hide()
            return
        want = getattr(pet, "bubble_pos", "above")
        area = pet.screen().availableGeometry() if pet.screen() else pet.area
        side = want
        if want == "above":
            lay = self.measure(text, "above")
            top = pet.y() + 26 - lay["h"]
            if top < area.top():
                side = "side"                      # no room above (top of the screen): go beside
        if side == "side":
            lay = self.measure(text, "side")
            right_x = pet.x() + 196
            side = "right" if right_x + lay["w"] <= area.right() else "left"
        else:
            side = "above"
        key = (text, side, pet.bubble_shape, pet.bubble_mode, pet.text_size)
        if key != self.key:
            self.key = key
            self.layout_ = self.measure(text, "above" if side == "above" else "side")
            self.side = side
            self.resize(self.layout_["w"], self.layout_["h"])
            self.update()
        w, h = self.layout_["w"], self.layout_["h"]
        if side == "above":
            x = pet.x() + 110 - w // 2
            y = pet.y() + 26 - h
        elif side == "right":
            x = pet.x() + 188
            y = pet.y() + 70 - h // 2
        else:
            x = pet.x() + 32 - w
            y = pet.y() + 70 - h // 2
        x = max(area.left(), min(area.right() - w, x))
        y = max(area.top(), min(area.bottom() - h, y))
        if (self.x(), self.y()) != (x, y):
            self.move(x, y)
        if not self.isVisible():
            self.show()
            if not IS_MAC:          # on a Mac, raising would make Digi the active app (steals typing)
                self.raise_()

    def measure(self, text, where):
        """Bubble size for this text. Above: wide and short. Beside: narrow and tall."""
        size = {"small": 9, "medium": 11, "large": 14}.get(getattr(self.pet, "text_size", "medium"), 11)
        thought = getattr(self.pet, "bubble_shape", "speech") == "thought"
        inner_w = 196 if where == "above" else 112
        max_h = 120 if where == "above" else 260
        flags = 0
        for fl in (Qt.AlignCenter, Qt.TextWordWrap):
            flags |= fl.value if hasattr(fl, "value") else int(fl)
        while True:
            f = QFont("Helvetica", size)
            r = QFontMetrics(f).boundingRect(QRect(0, 0, inner_w, 2000), flags, text)
            if r.height() <= max_h or size <= 8:
                break
            size -= 1
        th = max(r.height(), 20)
        bw = inner_w + 24
        bh = th + (26 if thought else 18)
        if where == "side":
            bh = max(bh, 70)
        if thought:                        # the bumpy edge needs a little more room
            bw += 16
            bh += 10
        P, T = self.PAD, self.TAIL
        if where == "above":
            w, h = bw + 2 * P, bh + 2 * P + T
        else:
            w, h = bw + 2 * P + T, bh + 2 * P
        return {"w": int(w), "h": int(h), "bw": bw, "bh": bh, "font": f}

    # ---- drawing
    def cloud(self, rect):
        """A thought-bubble cloud: a rounded box with bumps all around its edge."""
        path = QPainterPath()
        path.addRoundedRect(rect.adjusted(6, 6, -6, -6), 14, 14)
        r = 13.0
        def bumps(x0, y0, x1, y1):
            n = max(2, int(math.hypot(x1 - x0, y1 - y0) / (r * 1.45)))
            for i in range(n + 1):
                t = i / n
                cx, cy = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
                path.addEllipse(QPointF(cx, cy), r, r)
        L, T_, R, B = rect.left() + r, rect.top() + r, rect.right() - r, rect.bottom() - r
        bumps(L, T_, R, T_)
        bumps(R, T_, R, B)
        bumps(R, B, L, B)
        bumps(L, B, L, T_)
        # overlapping bumps must ADD up (winding), or the default odd-even rule punches holes
        # where they overlap and every circle's outline shows inside the bubble
        path.setFillRule(Qt.WindingFill)
        return path.simplified()

    def paintEvent(self, event):
        lay = self.layout_
        pet = self.pet
        if not lay or not pet.msg:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = getattr(pet, "bubble_mode", "light") == "dark"
        edge = QColor("#8a8a94") if dark else OUTLINE
        fill = QColor("#111114") if dark else QColor("white")
        P, T = self.PAD, self.TAIL
        bw, bh = lay["bw"], lay["bh"]
        if self.side == "above":
            box = QRectF(P, P, bw, bh)
        elif self.side == "right":
            box = QRectF(P + T, P, bw, bh)
        else:
            box = QRectF(P, P, bw, bh)
        thought = getattr(pet, "bubble_shape", "speech") == "thought"
        pen = QPen(edge, 3)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(QBrush(fill))
        if thought:
            body = self.cloud(box)
            # little circles trailing toward her head
            if self.side == "above":
                tip = QPointF(box.center().x() + 8, box.bottom())
                dots = [(tip + QPointF(-4, 9), 6), (tip + QPointF(-10, 19), 3.8)]
            elif self.side == "right":
                tip = QPointF(box.left(), box.center().y() + 6)
                dots = [(tip + QPointF(-8, 6), 5.5), (tip + QPointF(-17, 12), 3.5)]
            else:
                tip = QPointF(box.right(), box.center().y() + 6)
                dots = [(tip + QPointF(8, 6), 5.5), (tip + QPointF(17, 12), 3.5)]
            p.drawPath(body)
            for c, rr in dots:
                p.drawEllipse(c, rr, rr)
        else:
            body = QPainterPath()
            body.addRoundedRect(box, 12, 12)
            tail = QPainterPath()
            if self.side == "above":
                cx = box.center().x()
                tail.moveTo(cx - 10, box.bottom() - 2)
                tail.lineTo(cx + 2, box.bottom() + T - 4)
                tail.lineTo(cx + 12, box.bottom() - 2)
            elif self.side == "right":
                cy = box.center().y()
                tail.moveTo(box.left() + 2, cy - 9)
                tail.lineTo(box.left() - T + 4, cy + 4)
                tail.lineTo(box.left() + 2, cy + 9)
            else:
                cy = box.center().y()
                tail.moveTo(box.right() - 2, cy - 9)
                tail.lineTo(box.right() + T - 4, cy + 4)
                tail.lineTo(box.right() - 2, cy + 9)
            tail.closeSubpath()
            p.drawPath(body.united(tail).simplified())
        p.setPen(QPen(QColor("white") if dark else QColor("black")))
        p.setFont(lay["font"])
        opt = QTextOption(Qt.AlignCenter)
        opt.setWrapMode(QTextOption.WordWrap)
        p.drawText(box.adjusted(12, 8, -12, -8), pet.msg, opt)
        p.end()

    def mousePressEvent(self, e):
        # clicking the bubble: a reminder asks "got it / snooze", anything else just closes it
        pet = self.pet
        if pet.reminder_active:
            pet.reminder_menu(e.globalPosition().toPoint())
        else:
            pet.msg = None
            pet.msg_ticks = 0
            self.hide()


class ChoiceBar(QWidget):
    """A row of little buttons under Digi for answering her (Yes / Later / No, how long...)."""

    def __init__(self, pet, options, on_pick, active=None, big=False):
        super().__init__(None)
        self.pet = pet
        self.on_pick = on_pick
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | TOOL_FLAG
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(6)
        for label, key in options:
            b = QPushButton(label)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            if big:                             # round mode buttons: an icon over a little name
                on = key == active
                b.setFixedSize(62, 58) if key != "close" else b.setFixedSize(30, 30)
                b.setStyleSheet("QPushButton { border-radius: %dpx; font-size: 12px; font-weight: bold; "
                                "color: %s; background: %s; border: 2px solid %s; }"
                                "QPushButton:hover { background: %s; }"
                                % (15 if key == "close" else 18, "white" if on else "#3a3159",
                                   "#a99be0" if on else "white", "#6b5f93" if on else "#a99be0",
                                   "#9586d6" if on else "#efeaf9"))
            else:
                b.setStyleSheet("QPushButton { padding: 5px 12px; border-radius: 12px; font-size: 13px; "
                                "font-weight: bold; color: #3a3159; background: white; "
                                "border: 2px solid #a99be0; }"
                                "QPushButton:hover { background: #efeaf9; }")
            b.clicked.connect(lambda *a, k=key: self.pick(k))
            row.addWidget(b)
        self.adjustSize()
        self.follow()
        self.show()

    def pick(self, key):
        self.hide()
        self.deleteLater()
        self.on_pick(key)

    def follow(self):
        pet = self.pet
        area = pet.screen().availableGeometry() if pet.screen() else pet.area
        x = pet.x() + 110 - self.width() // 2
        y = pet.y() + 238
        if y + self.height() > area.bottom():
            y = pet.y() - self.height() - 4
        x = max(area.left(), min(area.right() - self.width(), x))
        if (self.x(), self.y()) != (x, y):
            self.move(x, y)


class RoomBubble(BubbleWin):
    """Her bubble inside the Customize room, over the Digi standing on the rug."""

    def __init__(self, pet, dialog):
        QWidget.__init__(self, dialog)
        self.pet = pet
        self.dialog = dialog
        self.key = None
        self.layout_ = None
        self.side = "above"
        self.hide()

    def follow(self):
        pet, dlg = self.pet, self.dialog
        text = pet.msg
        if not text:
            if self.isVisible():
                self.hide()
            return
        side = "above" if getattr(pet, "bubble_pos", "above") == "above" else "left"
        key = (text, side, pet.bubble_shape, pet.bubble_mode, pet.text_size)
        if key != self.key:
            self.key = key
            self.side = side
            self.layout_ = self.measure(text, "above" if side == "above" else "side")
            self.resize(self.layout_["w"], self.layout_["h"])
            self.update()
        w, h = self.layout_["w"], self.layout_["h"]
        pv = dlg.preview.geometry()
        if side == "above":
            x = pv.center().x() - w // 2
            y = pv.y() + int(pv.height() * 0.16) - h
        else:
            x = pv.x() + int(pv.width() * 0.2) - w
            y = pv.y() + int(pv.height() * 0.32) - h // 2
        x = max(4, min(dlg.width() - w - 4, x))
        y = max(4, min(dlg.height() - h - 4, y))
        if (self.x(), self.y()) != (x, y):
            self.move(x, y)
        if not self.isVisible():
            self.show()
        self.raise_()


class Pet(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | TOOL_FLAG
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)    # never steal your typing
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(220, 240)
        # while she's held and swinging, her window grows by this much so she isn't cut off;
        # x()/y()/move() below keep talking about her normal 220x240 spot either way
        self.pad_x = self.pad_y = 0

        self.area = QGuiApplication.primaryScreen().availableGeometry()
        self.px = float(self.area.right() - 260)
        self.py = float(self.area.bottom() - 260)
        self.move(int(self.px), int(self.py))

        self.t = 0
        self.blink = False
        self.blink_len = 0
        self.blink_cd = 80
        self.happy = 0
        self.msg = None
        self.msg_ticks = 0
        self.reminder_active = False
        self.last_reminder = ""
        self.hearts = []
        self.moved = False
        self.dragging = False
        self.surprised = False
        self.walking = False
        self.pause = 0
        self.wander = True
        self.vx = 0.0
        self.vy = 0.0
        self.idle_cd = random.randint(500, 1000)
        self.fired = set()

        # music + app reaction state
        self.music_playing = False
        self.singing = False
        self.was_singing = False
        self.sing_cd = 30
        self.sing_enabled = True
        self.dance_enabled = True
        self.react_enabled = True
        self.last_app = None
        self.app_last = {}
        self.js_error = False
        self.js_warned = False

        # extra feature state
        self.hovering = False
        self.hover_ticks = 0
        self.petting = False
        self.sleep_hours = in_sleep_hours()
        self.nap_until = 0
        self.sleepy = False
        self.bed_choice = "random"      # random, futon, petbed, dock, none
        self.test_bed = None
        self.bed = None                 # the bed she's in right now
        self.poof = 0
        # tarot + snacks + stretching
        self.tarot_enabled = True
        self.snacks_enabled = True
        self.activity = None            # {"kind", "phase", "until", ...}
        self.floor_sit = False
        self.card = None
        self.snack = None
        self.stretch_until = 0
        self.peek_ready = False
        self.bomb = None
        self.castle = None
        self.castles_enabled = True
        self.pout_until = 0
        # lots of little fun things
        self.fun = {"bubbles": True, "crystal": True, "teleport": True, "dnd_solo": True,
                    "cursor": True, "flowers": True, "cuddle": True, "typing": True,
                    "camera": True, "weather_report": True, "weather_react": True}
        self.soap = []
        self.crystal = None
        self.bouquet = None
        self.teleport = None
        self.flash = 0
        self.shy_until = self.scared_until = self.shiver_until = 0
        self.camera_until = self.umbrella_until = self.hot_until = self.boop_until = 0
        self.snow = False
        self.pat_times = []
        self.swat_cd = 0
        self.key_streak = 0
        self.last_key_burst = 0
        self.snap_pending = False
        self.weather = None              # {"temp": F, "code": n, "feels": F}
        self.weather_told = set()
        threading.Thread(target=self.screenshot_loop, daemon=True).start()
        self.outfit_style = "3d"         # "3d" (rendered) or "drawn"
        self.hair_color = None           # None = her original rendered hair
        self.hairstyle = "twintails"
        self.bubble_mode = "light"
        self.bubble_shape = "speech"      # speech or thought
        self.bubble_pos = "above"         # above her head, or beside her (tall and narrow)
        self.bubble_win = None
        self.nickname = ""                # what she calls you (empty = no name)
        self.intro_done = False           # the first-time hello tour (brand new Digis only)
        self.intro_step = -1
        self.intro_talking = False
        self.place = None                 # {"name", "lat", "lon"} for the weather
        self.units = "F"
        self.dnd_days = list(DND_DAYS)    # every day with a game (kept in step with dnd_games)
        self.dnd_games = []               # your D&D games (Customize -> D&D)
        self.dnd_opts = {"use_name": True, "dress": True}
        self.dnd_init = {"order": [], "turn": 0, "round": 1, "manual": False}   # [[name, total, mod, roll]]
        self.dnd_said = set()             # heads-ups already given
        self.dnd_cache = (0.0, None)
        self.birthdays = []               # [{"name", "month", "day"}] she reminds you of
        self.my_birthday = None           # {"month", "day"}: she celebrates you!
        self.med_end = None               # meditation: when it ends
        self.med_start = None
        self.med_minutes_set = 0
        self.med_guide = True             # "breathe in / hold / out" in her bubble
        self.med_days = []                # dates she meditated with you (YYYY-MM-DD)
        self.med_total = 0                # minutes, all time
        self.med_pending = []             # reminders that waited until she was done
        self.med_phase = -1
        self.med_sound = "none"           # background sound while meditating
        self.med_chime = "bell"           # the chime that starts a meditation
        self.med_volume = 0.5
        self.sound_player = None
        self.sound_key = None
        self.preview_key = None
        self.preview_start = 0.0
        self.preview_until = 0.0
        self.med_time = None              # "HH:MM": she invites you to meditate every day at this time
        self.med_asked_day = None         # the day she already asked (and you said no / did it)
        self.med_ask_at = None            # "Later": ask again at this time
        self.med_asking = False           # walking to the middle and asking right now
        self.med_asked_since = 0
        self.med_awaiting_more = False    # time's up: "keep going?"
        self.choice_bar = None
        self.rps = {"you": 0, "digi": 0, "tie": 0}   # rock-paper-scissors, all time
        self.rps_game = [0, 0]                       # this game: you, Digi
        self.rps_busy = False                        # mid "rock... paper... scissors..."
        self.trivia = None                           # a trivia round that's going on
        self.trivia_busy = False                     # between questions
        self.trivia_best = {}                        # best score per category
        self.trivia_mine = []                        # your own questions
        self.trivia_seen = set()                     # asked lately (so they don't repeat soon)
        self.choice_big = False
        self.choice_timeout = None
        self.choice_pick = None
        self.choice_since = 0.0
        self.menu_open = False            # one of her right-click menus is open: she holds still
        self.sleep_hours_set = list(SLEEP_HOURS)
        self.apply_personal(PERSONAL)     # someone's own starting setup, if there is one
        self.text_size = "medium"
        self.outline = "glow"             # soft white outline so she shows up on dark windows
        self.glow_told = False            # has she explained her glow yet?
        self.bottom = "skirt"
        self.bottom_cache = {}           # {bottom: {state: [QPixmap or None]}} for the one she wears
        self.tint_cache = {}
        self.custom_win = None
        self.outfit_cache = {}
        self.acc_mode = "auto"
        self.load_custom()
        threading.Thread(target=self.weather_loop, daemon=True).start()   # after her city is known
        self.focus_end = None
        self.break_end = None
        self.pomo = False
        self.timers = []
        self.eye_enabled = True
        self.eye_last = time.time()
        self.batt_pct = None
        self.on_battery = False
        self.batt_warned = False
        self.batt_was_low = False

        # window + mouse-following state
        self.windows_enabled = True
        self.follow_enabled = True
        self.mode = "wander"      # wander, follow, perch, peek
        self.mode_until = time.time() + random.uniform(10, 20)
        self.cur_window = None
        self.clip_rect = None
        self.peek_side = None
        self.peek_x = 0
        self.pdir = 1
        self.jump = 0

        # welcome back, steam, greetings, to-do, art
        self.welcome_enabled = True
        self.was_locked = False
        self.lock_since = None
        self.last_check = time.time()
        self.last_welcome = 0
        self.steam_enabled = True
        self.game_mode = False
        self.steam_running = False
        self.steam_game = False
        self.prev_steam = None
        self.prev_game = None
        self.cheer_next = 0
        self.greeted = None
        self.todos = self.load_todos()
        self.cycle = self.load_cycle()
        self.reminders = load_reminders()
        # ball, gravity, dice, stream, water
        self.ball = None
        self.ball_until = 0
        self.kicks = 0
        self.kick_cd = 0
        self.gravity_enabled = True
        self.falling = False
        self.fall_v = 0.0
        self.fall_floor = 0
        self.fall_window = None
        self.dice = []
        self.dice_done_at = None
        self.roll_spec = None
        self.roll_results = []
        self.last_custom = "1d20"
        self.sitting = False
        self.sit_until = 0
        self.want_sit = False
        self.stream_enabled = True
        self.stream_manual = False
        self.movie = False              # movie mode: popcorn in the corner
        self.gaming = False             # video game mode: she plays games in the corner too
        self.dnd_mode = False           # D&D mode: she plays solo D&D in the corner with her dragon book
        self.dnd_mode_next = 0
        self.gaming_cheer = 0
        self.obs_open = False
        self.streaming = False
        self.water = self.load_water()
        self.reminder_win = None
        self.birthday_win = None
        self.bday_checked = None          # day we last did the birthday reminders
        self.art = self.load_art()
        self.hair_layers = {}
        self.frames = self.load_frames()
        self.held_ticks = 0      # how long she's been held up
        self.swing = 0.0         # dangle angle (degrees)
        self.swing_v = 0.0
        self.last_drag_x = None

        # voice
        self.ears = None
        self.listen_always = False
        self.ptt = False                 # push-to-talk is happening
        self.tap_talk = 0                # double-click listening started at this tick
        self.ptt_waiting = 0             # waiting for final words after release
        self.voice_text = ""
        self.voice_changed = 0
        self.voice_handled = ""
        self.attentive_until = 0
        self.press_pos = None
        self.shoo_until = 0
        self.shoo_target = None
        self.sing_until = 0
        self.roll_kind = None
        self.ptt_timer = QTimer(self)
        self.ptt_timer.setSingleShot(True)
        self.ptt_timer.timeout.connect(self.start_ptt)
        if dv is not None:
            self.ears = dv.Ears()
            self.ears.heard.connect(self.on_heard)
            self.ears.status.connect(self.on_ear_status)

        self.pick_direction()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(40)

        threading.Thread(target=self.music_loop, daemon=True).start()
        threading.Thread(target=self.battery_loop, daemon=True).start()
        threading.Thread(target=self.steam_loop, daemon=True).start()
        QTimer.singleShot(1500, self.greet)

    # ---------- updates ----------
    def code_dir(self):
        return os.path.dirname(os.path.abspath(__file__))

    def frames_version(self):
        try:
            with open(os.path.join(self.code_dir(), "pet_frames", "frames_version.txt")) as f:
                return int(f.read().strip() or 1)
        except Exception:
            return 1

    def frame_patches(self, info):
        """New outfit pictures that come as small add-on packs (newer than the pictures she has)."""
        have = self.frames_version()
        if int(info.get("frames_version", 1)) > have:
            have = int(info.get("frames_version", 1))        # a full new set would come first
        out = []
        for p in info.get("frames_patches", []) or []:
            try:
                if int(p["version"]) > have and str(p["url"]).startswith("https://"):
                    out.append(p)
            except Exception:
                pass
        return sorted(out, key=lambda p: int(p["version"]))

    def fetch(self, url, timeout=20):
        import urllib.request
        req = urllib.request.Request(url + ("&" if "?" in url else "?") + "t=%d" % time.time(),
                                     headers={"User-Agent": "DigiPal"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception:
            # some Mac Pythons are missing web certificates
            import ssl
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return r.read()

    def check_updates(self, manual=False):
        """Asks GitHub if there's a newer Digi (in the background)."""
        def work():
            try:
                info = json.loads(self.fetch(UPDATE_RAW + "version.json").decode())
            except Exception as ex:
                print("update check failed:", ex, file=sys.stderr, flush=True)
                info = None
            self.update_result = (info, manual)
        self.update_result = None
        threading.Thread(target=work, daemon=True).start()
        if manual:
            self.say("Let me check for updates...", 2000)

    def update_tick(self):
        """Runs every second: looks at what the update check found."""
        res = getattr(self, "update_result", None)
        if res is None:
            return
        self.update_result = None
        info, manual = res
        if info is None:
            if manual:
                self.say("Hmm, I couldn't check for updates. Are you online?", 3000)
            return
        newer = int(info.get("version", 0)) > APP_VERSION
        new_frames = int(info.get("frames_version", 1)) > self.frames_version()
        if newer or new_frames or self.frame_patches(info):
            self.update_info = info
            self.say("\u2728 There's an update for me! Right-click me \u2192 Update Digi", 6000)
            self.happy = 30
        elif manual:
            self.say("I'm all up to date! \u2665", 2500)

    def do_update(self):
        info = getattr(self, "update_info", None)
        if not info:
            return
        new_frames = int(info.get("frames_version", 1)) > self.frames_version()
        get_frames = False
        if new_frames and info.get("frames_url"):
            mb = info.get("frames_mb", 800)
            ans = QMessageBox.question(None, "Update Digi",
                                       "This update has new pictures for Digi (new looks!).\n"
                                       f"That's a big download (about {mb} MB).\n\nDownload them now?")
            get_frames = ans == QMessageBox.Yes
        patches = self.frame_patches(info)
        if patches and (get_frames or not new_frames):
            mb = sum(int(p.get("mb", 100)) for p in patches)
            ans = QMessageBox.question(None, "Update Digi",
                                       "There are new outfits for Digi!\n"
                                       f"They're a download of about {mb} MB.\n\nDownload them now?")
            if ans != QMessageBox.Yes:
                patches = []
        else:
            patches = []
        if int(info.get("version", 0)) <= APP_VERSION and not get_frames and not patches:
            return
        self.say("Updating... be right back! \U0001F527", 30000)
        self.update_progress = None

        def work():
            import tempfile
            import zipfile
            import shutil
            import urllib.request
            import urllib.parse
            here = self.code_dir()
            try:
                # 1. her code: download everything first, then swap it in
                tmp = tempfile.mkdtemp(prefix="digi_update_")
                for rel in info.get("files", []):
                    if ".." in rel or rel.startswith(("/", "\\")):
                        continue
                    import urllib.parse
                    data = self.fetch(UPDATE_RAW + urllib.parse.quote(rel.replace("\\", "/")), timeout=60)
                    dst = os.path.join(tmp, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(dst, "wb") as f:
                        f.write(data)
                for rel in info.get("files", []):
                    src = os.path.join(tmp, rel)
                    if os.path.exists(src):
                        dst = os.path.join(here, rel)
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copyfile(src, dst)
                # 2. her pictures (only when there are new ones and you said yes)
                if get_frames:
                    self.update_progress = "Downloading my new looks..."
                    zpath = os.path.join(tmp, "pet_frames.zip")
                    import urllib.request
                    req = urllib.request.Request(info["frames_url"], headers={"User-Agent": "DigiPal"})
                    with urllib.request.urlopen(req, timeout=60) as r, open(zpath, "wb") as f:
                        total = int(r.headers.get("Content-Length") or 0)
                        got = 0
                        while True:
                            chunk = r.read(1 << 20)
                            if not chunk:
                                break
                            f.write(chunk)
                            got += len(chunk)
                            if total:
                                self.update_progress = f"Downloading my new looks... {got * 100 // total}%"
                    self.update_progress = "Unpacking..."
                    out = os.path.join(tmp, "frames")
                    with zipfile.ZipFile(zpath) as z:
                        z.extractall(out)
                    new = os.path.join(out, "pet_frames")
                    if os.path.isdir(new):
                        old = os.path.join(here, "pet_frames")
                        trash = os.path.join(here, "pet_frames_old")
                        shutil.rmtree(trash, ignore_errors=True)
                        if os.path.isdir(old):
                            os.rename(old, trash)
                        shutil.move(new, old)
                        with open(os.path.join(old, "frames_version.txt"), "w") as f:
                            f.write(str(info.get("frames_version", 1)))
                        shutil.rmtree(trash, ignore_errors=True)
                # 3. add-on outfit packs: unpacked INTO her pictures (nothing else is replaced)
                for i, pk in enumerate(patches):
                    self.update_progress = "Downloading new outfits..."
                    zpath = os.path.join(tmp, "patch_%d.zip" % i)
                    req = urllib.request.Request(pk["url"], headers={"User-Agent": "DigiPal"})
                    with urllib.request.urlopen(req, timeout=60) as r, open(zpath, "wb") as f:
                        total = int(r.headers.get("Content-Length") or 0)
                        got = 0
                        while True:
                            chunk = r.read(1 << 20)
                            if not chunk:
                                break
                            f.write(chunk)
                            got += len(chunk)
                            if total:
                                self.update_progress = f"Downloading new outfits... {got * 100 // total}%"
                    self.update_progress = "Unpacking..."
                    out = os.path.join(tmp, "patch_%d" % i)
                    with zipfile.ZipFile(zpath) as z:
                        for name in z.namelist():
                            if ".." in name or name.startswith(("/", "\\")):
                                raise RuntimeError("bad file in outfit pack")
                        z.extractall(out)
                    new = os.path.join(out, "pet_frames")
                    if os.path.isdir(new):
                        old = os.path.join(here, "pet_frames")
                        shutil.copytree(new, old, dirs_exist_ok=True)
                        with open(os.path.join(old, "frames_version.txt"), "w") as f:
                            f.write(str(pk["version"]))
                shutil.rmtree(tmp, ignore_errors=True)
                self.update_progress = "done"
            except Exception as ex:
                print("update failed:", ex, file=sys.stderr, flush=True)
                self.update_progress = "failed: " + str(ex)[:60]

        threading.Thread(target=work, daemon=True).start()

    def update_progress_tick(self):
        st = getattr(self, "update_progress", None)
        if not st:
            return
        if st == "done":
            self.update_progress = None
            self.say("All updated! Restarting~ \u2728", 3000)
            QTimer.singleShot(1500, self.restart_self)
        elif st.startswith("failed"):
            self.update_progress = None
            self.say("Oops, the update didn't work~ " + st[8:], 5000)
        else:
            self.msg = st
            self.msg_ticks = 60

    def restart_self(self):
        if APP_LOCK is not None:
            APP_LOCK.unlock()
        cmd = self.launch_command()
        try:
            if IS_WIN:
                subprocess.Popen(cmd, creationflags=0x00000008 | 0x00000200, close_fds=True)
            elif cmd[0] == "/usr/bin/open":
                subprocess.Popen(["/bin/sh", "-c", "sleep 2; open -a '%s'" % cmd[-1]])
            else:
                subprocess.Popen(cmd, start_new_session=True)
        except Exception as ex:
            print("restart failed:", ex, file=sys.stderr, flush=True)
        QApplication.quit()

    # ---------- hello! ----------
    def greet(self, tries=0):
        """Says hi when the app opens, depending on the time of day."""
        if self.reminder_active:
            return
        if not self.intro_done:             # brand new Digi: the hello tour instead
            self.start_intro()
            return
        if self.msg and tries < 3:          # she's saying something else - say hi right after
            QTimer.singleShot(4000, lambda: self.greet(tries + 1))
            return
        now = datetime.now()
        h, wd = now.hour, now.weekday()
        # ", name" when you've told her what to call you (Customize -> "Call me")
        nm = (", " + self.call_name()) if self.call_name() else ""
        if 5 <= h < 12:
            lines = [f"Good morning{nm}! \u2600\ufe0f", "Morning~ Did you have breakfast?",
                     "Rise and shine! Let's have a good day!"]
        elif 12 <= h < 17:
            lines = [f"Good afternoon{nm}!", "Hiii! How's your day going?", f"Hey hey{nm}! I missed you~"]
        elif 17 <= h < 22:
            lines = [f"Good evening{nm}~", f"Welcome back{nm}! \U0001F49C", "Evening! Long day?"]
        else:
            lines = ["You're up late! Don't stay up too long~", "Hi night owl! \U0001F319",
                     "Can't sleep? I'll keep you company~"]
        if wd == 4:
            lines.append("It's Friday!! \U0001F389")
        elif wd == 0 and h < 17:
            lines.append("Happy Monday! We've got this!")
        self.happy = 40
        self.say(random.choice(lines), 4000)
        if self.outline == "glow" and not self.glow_told:
            # once: explain the new glow (and where to turn it off)
            self.glow_told = True
            self.save_custom()
            QTimer.singleShot(4500, lambda: self.say(
                "See my glow? \u2728 It's so I don't get lost in dark mode! "
                "(You can turn it off in Customize)", 6000))

    # ---------- the first-time tour: she introduces herself and shows you around ----------
    def start_intro(self):
        # drop whatever she was doing: the tour has her full attention
        if self.activity:
            self.end_activity(quiet=True)
        if self.ball:
            self.end_ball()
        if self.mode == "peek":
            self.set_mode("wander", 30)
        self.intro_step = 0
        self.happy = 40
        self.jump = 20
        self.intro_show()

    def intro_show(self):
        i = self.intro_step
        if i < 0 or i >= len(INTRO_STEPS):
            return
        text, buttons = INTRO_STEPS[i]
        if text == "NAME":
            self.tour_say("First things first... what should I call you? \U0001F60A", 120000)
            QTimer.singleShot(400, self.intro_ask_name)
            return
        self.tour_say(text, 120000)
        if i < len(INTRO_STEPS) - 1:
            buttons = buttons + [("Skip tour", "skip")]
        self.show_choices(buttons, self.intro_pick)

    def intro_ask_name(self):
        dlg = QInputDialog()
        dlg.setWindowTitle("Nice to meet you!")
        dlg.setLabelText("What should Digi call you?")
        dlg.setTextValue(self.nickname)
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
        ok = dlg.exec()
        name = dlg.textValue().strip()[:24] if ok else ""
        if name:
            self.nickname = name
            self.save_custom()
            self.tour_say(f"{name}! What a lovely name! Nice to meet you~ \U0001F49C", 3500)
        else:
            self.tour_say("That's okay! You can tell me later in Customize \u2192 Me~", 3500)
        self.happy = 40
        self.intro_step += 1
        QTimer.singleShot(3600, self.intro_show)

    def intro_pick(self, key):
        if key == "skip" or key == "done":
            self.intro_done = True
            self.intro_step = -1
            self.save_custom()
            self.say("Okay! I'll be right here if you need me \U0001F49C" if key == "skip"
                     else "Yay! Let's be friends! \U0001F49C", 3000)
            self.happy = 50
            self.jump = 20
            return
        if key == "customize":
            self.open_customize(0)
        elif key == "lists":
            self.open_customize(3)
        self.intro_step += 1
        self.intro_show()

    # ---------- your own art ----------
    def load_art(self):
        folder = os.path.dirname(os.path.abspath(__file__))
        art = {}
        for name in ART_NAMES:
            path = os.path.join(folder, f"pet_{name}.png")
            if os.path.exists(path):
                pm = QPixmap(path)
                if not pm.isNull():
                    art[name] = pm
        return art if "idle" in art else {}

    # ---------- 3D frames rendered in Blender ----------
    def load_frames(self):
        here = os.path.dirname(os.path.abspath(__file__))
        folders = [os.path.join(here, "pet_frames"),
                   os.path.expanduser("~/Downloads/pet_frames")]
        for folder in folders:
            if not os.path.isdir(folder):
                continue
            frames = {}
            hair = {}
            for name in sorted(os.listdir(folder)):
                if not name.endswith(".png") or "_" not in name:
                    continue
                state = name.rsplit("_", 1)[0]
                pm = QPixmap(os.path.join(folder, name))
                if not pm.isNull():
                    frames.setdefault(state, []).append(pm)
                    hp = os.path.join(folder, "hair", name)
                    hair.setdefault(state, []).append(QPixmap(hp) if os.path.exists(hp) else None)
            if "idle" in frames:
                self.hair_layers = hair
                self.frames_folder = folder
                return frames
        return {}

    def frame_for(self, happy_eyes):
        # (state, ticks per frame) in order of priority
        flip = False
        peek = self.peek_state()
        if peek:
            want = [(peek, 6)]
            flip = self.peek_side == "left"
        elif self.bed and not self.dragging and ("sleep_" + self.bed) in self.frames:
            want = [("sleep_" + self.bed, 6)]
        elif self.pose_now():
            # (asked once more: a pose can run out between the two checks, so keep a fallback)
            want = [self.pose_now() or ("idle", 5)]
        elif time.time() < self.pout_until and not self.dragging and "blink" in self.frames:
            want = [("blink", 1)]
        elif time.time() < self.stretch_until and not self.dragging:
            want = [("stretch", 4), ("happy", 3)]
        elif self.med_end and not self.dragging:
            want = [("meditate", 6), ("sitfloor", 6)]
        elif self.movie_settled():
            want = [("sitfloor", 5)]
        elif self.gaming and self.corner_settled():
            want = [("gaming", 4), ("sitfloor", 5)]
        elif self.dnd_mode and self.corner_settled():
            want = [("sitfloor", 5)]                # sitting with her dragon book, rolling dice
        elif self.floor_sit and not self.dragging:
            want = [("sitfloor", 5)]
        elif self.sitting and self.mode == "perch" and not self.dragging:
            want = [("sit", 4)]
        elif self.dragging and self.moved and not self.surprised:
            want = [("held", 6), ("surprised", 5)]
        elif self.surprised:
            want = [("surprised", 5), ("happy", 3)]
        elif self.sleepy:
            want = [("sleepy", 6)]
        elif self.singing:
            want = [("sing", 4), ("happy", 3)]
        elif self.walking:
            want = [("walk", 3)]
        elif happy_eyes:
            want = [("happy", 3)]
        elif self.blink:
            want = [("blink", 1)]
        else:
            want = []
        want.append(("idle", 5))
        acc = self.current_accessory()
        dressed = None
        if acc and self.outfit_style == "3d" and not self.bed:
            dressed = self.outfit_frames(acc)
        for state, speed in want:
            if state in self.frames:
                seq = self.frames[state]
                n = self.t // speed
                if dressed and state in dressed:
                    oseq = dressed[state]
                    k = n % len(oseq)
                    if self.layered_hair():
                        self.cur_hair = self.style_layer(getattr(self, "outfit_folder", None), state, k)
                    else:
                        hl = getattr(self, "outfit_hair", {}).get(state) or []
                        self.cur_hair = hl[k] if k < len(hl) else None
                    self.cur_bottom = self.bottom_for(state, k)
                    return oseq[k], True, flip, state
                k = n % len(seq)
                if self.layered_hair():
                    self.cur_hair = self.style_layer(self.frames_folder, state, k)
                else:
                    hl = self.hair_layers.get(state) or []
                    self.cur_hair = hl[k] if k < len(hl) else None
                self.cur_bottom = self.bottom_for(state, k)
                return seq[k], False, flip, state
        self.cur_hair = self.style_layer(getattr(self, "frames_folder", None), "idle", 0)
        self.cur_bottom = self.bottom_for("idle", 0)
        return self.frames["idle"][0], False, False, "idle"

    def peek_state(self):
        if (self.mode != "peek" or self.peek_side is None or self.dragging
                or not self.peek_ready):
            return None
        st = "peektop" if self.peek_side == "top" else "peekside"
        return st if st in self.frames else None

    def art_state(self, happy_eyes):
        if self.surprised:
            order = ["surprised", "happy", "idle"]
        elif self.sleepy:
            order = ["sleepy", "blink", "idle"]
        elif happy_eyes:
            order = ["happy", "idle"]
        elif self.blink:
            order = ["blink", "idle"]
        else:
            order = ["idle"]
        for name in order:
            if name in self.art:
                return name
        return "idle"

    # ---------- cycle tracker (off unless switched on; lives only in CYCLE_FILE) ----------
    def load_cycle(self):
        data = {"enabled": False, "starts": [], "period_len": 5, "notify": True, "said": ""}
        try:
            with open(CYCLE_FILE, "r") as f:
                data.update(json.load(f))
        except Exception:
            pass
        return data

    def save_cycle(self):
        try:
            with open(CYCLE_FILE, "w") as f:
                json.dump(self.cycle, f)
        except Exception:
            pass

    def cycle_started(self, day):
        starts = sorted(set(self.cycle.get("starts", [])) | {day.isoformat()})
        self.cycle["starts"] = starts[-24:]
        self.save_cycle()
        self.say("Noted \U0001F338 Be gentle with yourself~", 2600)

    def cycle_guess(self):
        """(last start, average length, next start) from the last few cycles, or None."""
        starts = [date.fromisoformat(x) for x in self.cycle.get("starts", [])]
        if not starts:
            return None
        gaps = [(b - a).days for a, b in zip(starts, starts[1:]) if 15 <= (b - a).days <= 60]
        avg = round(sum(gaps[-6:]) / len(gaps[-6:])) if gaps else 28
        last = starts[-1]
        nxt = last + timedelta(days=avg)
        while nxt < date.today() - timedelta(days=3):   # a start wasn't logged: guess the next one
            nxt += timedelta(days=avg)
        return last, avg, nxt

    def cycle_summary(self):
        g = self.cycle_guess()
        if not g:
            return "Tap \"Started today\" when your next period starts, and I'll start keeping track!"
        last, avg, nxt = g
        today = date.today()
        n = (nxt - today).days
        day_in = (today - last).days + 1
        lines = [f"Last started: {last:%b} {last.day} (today is day {day_in})"]
        if n > 1:
            lines.append(f"Next might start around {nxt:%b} {nxt.day} (in about {n} days)")
        elif n == 1:
            lines.append("Next might start around tomorrow")
        elif n == 0:
            lines.append("Next might start around today")
        else:
            lines.append(f"Next was expected around {nxt:%b} {nxt.day}")
        lines.append(f"Usual cycle: about {avg} days" + ("" if len(self.cycle["starts"]) > 1
                                                        else " (a guess until I've seen two)"))
        return "\n".join(lines)

    def check_cycle(self):
        """A gentle heads-up a couple of days before, on the day, and a kind word during. Only to
        you: never while streaming or when OBS is open, and never as a big reminder pop-up."""
        c = self.cycle
        if not c.get("enabled") or not c.get("notify"):
            return
        now = datetime.now()
        today = now.date()
        if c.get("said") == today.isoformat() or now.hour < 10 or self.sleep_hours:
            return
        if self.streaming or self.obs_open or self.msg or self.reminder_active:
            return
        g = self.cycle_guess()
        if not g:
            return
        last, avg, nxt = g
        n = (nxt - today).days
        in_period = 0 <= (today - last).days < int(c.get("period_len", 5))
        line = None
        if n == 2:
            line = random.choice(CYCLE_HEADSUP)
        elif n == 0:
            line = random.choice(CYCLE_TODAY)
        elif in_period and (today - last).days in (0, 1):
            line = random.choice(CYCLE_CARE)
        c["said"] = today.isoformat()
        self.save_cycle()
        if line:
            self.say(line, 6000)
            self.happy = 15

    # ---------- to-do list ----------
    def load_todos(self):
        try:
            with open(TODO_FILE, "r") as f:
                data = json.load(f)
            return [str(x) for x in data] if isinstance(data, list) else []
        except Exception:
            return []

    def save_todos(self):
        try:
            with open(TODO_FILE, "w") as f:
                json.dump(self.todos, f)
        except Exception:
            pass

    def add_todo(self):
        QTimer.singleShot(50, self.add_todo_now)

    def add_todo_now(self):
        text, ok = QInputDialog.getText(None, "To-do", "What's the task?")
        if ok and text.strip():
            self.todos.append(text.strip()[:80])
            self.save_todos()
            self.say("Added! You've got this~", 2200)
            self.happy = 15

    def finish_todo(self, i):
        if 0 <= i < len(self.todos):
            self.todos.pop(i)
            self.save_todos()
            left = len(self.todos)
            if left:
                self.say(f"Yay! Done! {left} left~", 2800)
            else:
                self.say("Yay! All done! You did it!", 3000)
            self.happy = 40
            self.jump = 20
            for _ in range(3):
                self.hearts.append([random.randint(80, 140), 90, 0, "\u2665"])

    def clear_todos(self):
        self.todos = []
        self.save_todos()
        self.say("Cleared!", 1500)

    # ---------- start at login ----------
    def set_autostart(self, value):
        if HELPER:
            try:
                cmd = " ".join('"%s"' % c for c in self.launch_command())
                W.set_autostart(value, cmd)
                self.say("I'll start when you log in~" if value else "Okay, no auto-start.", 3000)
            except Exception:
                self.say("Hmm, I couldn't set that up.", 3000)
            return
        try:
            if value:
                os.makedirs(os.path.dirname(LAUNCH_AGENT), exist_ok=True)
                data = {
                    "Label": "com.deskpet.companion",
                    "ProgramArguments": self.launch_command(),
                    "RunAtLoad": True,
                    "KeepAlive": False,
                }
                with open(LAUNCH_AGENT, "wb") as f:
                    plistlib.dump(data, f)
                self.say("I'll start when you log in~", 3000)
            else:
                if os.path.exists(LAUNCH_AGENT):
                    os.remove(LAUNCH_AGENT)
                self.say("Okay, no auto-start.", 2000)
        except Exception:
            self.say("Hmm, I couldn't set that up.", 3000)

    # ---------- mouse ----------
    def enterEvent(self, e):
        self.hovering = True
        self.hover_ticks = 0

    def leaveEvent(self, e):
        self.hovering = False
        self.hover_ticks = 0
        self.petting = False

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and (e.modifiers() & Qt.ShiftModifier):
            self.moved = False
            self.skip_release = True
            self.open_customize()
            return
        if e.button() == Qt.LeftButton:
            self.drag_offset = e.globalPosition().toPoint() - QPoint(self.x(), self.y())   # her normal spot
            self.dragging = True
            self.moved = False
            self.petting = False
            self.hover_ticks = 0
            self.press_pos = e.globalPosition().toPoint()
            if self.ears is not None:
                self.ptt_timer.start(350)      # hold still to talk
            if self.mode != "wander":
                self.set_mode("wander", random.uniform(10, 20))

    # ---- room to swing: grow the window while she's held, shrink it once she hangs still ----
    SWING_PAD_X, SWING_PAD_Y = 85, 25

    def x(self):
        return QWidget.x(self) + self.pad_x

    def y(self):
        return QWidget.y(self) + self.pad_y

    def move(self, *a):
        pt = QPoint(a[0], a[1]) if len(a) == 2 else QPoint(a[0])
        QWidget.move(self, pt - QPoint(self.pad_x, self.pad_y))

    def set_swing_room(self, on):
        want = (self.SWING_PAD_X, self.SWING_PAD_Y) if on else (0, 0)
        if (self.pad_x, self.pad_y) == want:
            return
        x, y = self.x(), self.y()                 # her normal spot stays put
        self.pad_x, self.pad_y = want
        QWidget.setGeometry(self, x - self.pad_x, y - self.pad_y,
                            220 + 2 * self.pad_x, 240 + self.pad_y)
        self.update()

    def mouseMoveEvent(self, e):
        if self.ptt:
            return
        if self.dragging and (e.buttons() & Qt.LeftButton):
            if not self.moved:
                gp = e.globalPosition().toPoint()
                if self.press_pos is not None and (gp - self.press_pos).manhattanLength() < 12:
                    return                       # tiny wiggle, not a drag yet
                self.ptt_timer.stop()
                self.surprised = True
                self.set_swing_room(True)
                if not self.reminder_active:
                    self.say("Eep!", 1500)
            pos = e.globalPosition().toPoint() - self.drag_offset
            if self.last_drag_x is not None:
                # body lags behind the hand, like a pendulum
                self.swing_v += (pos.x() - self.last_drag_x) * 0.35
            self.last_drag_x = pos.x()
            self.px, self.py = float(pos.x()), float(pos.y())
            self.move(pos)
            self.moved = True

    def mouseReleaseEvent(self, e):
        if getattr(self, "skip_release", False):
            self.skip_release = False
            return
        if e.button() == Qt.LeftButton:
            self.ptt_timer.stop()
            if self.ptt:
                self.ptt = False
                self.dragging = False
                self.ptt_waiting = self.t
                # keep recording a moment so the last word isn't cut off
                QTimer.singleShot(600, self.ears.finish_talking)
                return
            if self.tap_talk:
                self.dragging = False
                return
            self.dragging = False
            self.surprised = False
            self.held_ticks = 0
            self.last_drag_x = None
            if self.moved:
                if self.gravity_enabled:
                    self.start_fall()
                else:
                    self.happy = 25
                    if not self.reminder_active:
                        self.say("Whee!", 1200)
            else:
                if self.reminder_active:
                    self.reminder_menu(e.globalPosition().toPoint())
                elif self.is_nose(e.position()):
                    self.boop()
                else:
                    self.poke()

    def reminder_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Got it!", self.dismiss_reminder)
        menu.addAction("Snooze 10 minutes", lambda *a: self.snooze(10))
        menu.addAction("Snooze 30 minutes", lambda *a: self.snooze(30))
        self.run_menu(menu, pos)

    def dismiss_reminder(self):
        self.msg = None
        self.reminder_active = False
        self.say("Okay!", 1500)
        self.happy = 25

    def snooze(self, minutes):
        text = self.last_reminder or "Reminder"
        self.timers.append([time.time() + minutes * 60, text])
        self.msg = None
        self.reminder_active = False
        self.say(f"Okay! Again in {minutes_label(minutes)}~", 2200)

    def show_steam_status(self):
        self.say(f"Steam: {self.steam_running}, game: {self.steam_game}", 5000)

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.addAction("\u2728 Customize Digi...", lambda *a: self.open_customize())
        menu.addSeparator()
        menu.addAction("Say hi", self.poke)
        menu.addAction("Come here!", self.come_here)
        names = {"gaming": "Video games", "dnd": "Solo D&D", "movie": "Movie", "stream": "Stream",
                 "cheer": "Cheer me on"}
        now_mode = self.current_mode()
        menu.addAction("\U0001F3AE Modes..." + ("  (now: %s)" % names[now_mode] if now_mode in names else ""),
                       self.show_modes)
        menu.addSeparator()

        if self.med_end:
            menu.addAction("\U0001F9D8 Stop meditating", lambda: self.stop_meditation(early=True))
        else:
            mm = menu.addMenu("\U0001F9D8 Meditate")
            for m in MED_CHOICES:
                mm.addAction(minutes_label(m), lambda *a, m=m: self.start_meditation(m))
            mm.addSeparator()
            self.add_toggle(mm, "Breathing guide (in / hold / out)", self.med_guide, self.set_med_guide)
            mm.addAction("My meditation stats", self.say_med_stats)

        # timers
        if self.focus_end or self.break_end:
            menu.addAction("\u23F0 Stop timer", self.stop_focus)
        else:
            tmr = menu.addMenu("\u23F0 Timers")
            fm = tmr.addMenu("Focus timer")
            fm.addAction(f"Pomodoro ({POMODORO_FOCUS} focus + {POMODORO_BREAK} break)",
                         self.start_pomodoro)
            fm.addSeparator()
            for m in TIMER_CHOICES:
                fm.addAction(minutes_label(m), lambda *a, m=m: self.start_focus(m))
            rm = tmr.addMenu("Remind me in...")
            for m in TIMER_CHOICES:
                rm.addAction(minutes_label(m), lambda *a, m=m: self.ask_reminder(m))

        # lists: the quick things here, everything else on the Lists tab
        w = self.water_today()
        lm = menu.addMenu("\U0001F4CB My lists")
        lm.addAction(f"I drank water! ({w}/{self.water['goal']})", self.drink)
        lm.addAction("Add a to-do...", self.add_todo)
        if self.todos:
            dm2 = lm.addMenu(f"Check off a to-do ({len(self.todos)})")
            for i, task in enumerate(self.todos):
                dm2.addAction(task[:30], lambda *a, i=i: self.finish_todo(i))
        lm.addSeparator()
        lm.addAction("Open my lists (reminders, birthdays...)", lambda *a: self.open_customize(3))

        # play
        pm = menu.addMenu("\U0001F3B2 Play")
        if self.ball:
            pm.addAction("Put the ball away", self.end_ball)
        else:
            pm.addAction("Toss a ball!", self.toss_ball)
        pm.addAction("\u270A Rock, paper, scissors", self.play_rps)
        pm.addAction("\U0001F9E0 Trivia", self.play_trivia)
        pm.addAction("Throw a bomb! \U0001F4A3", self.throw_bomb)
        dm = pm.addMenu("Roll dice")
        for sides in DICE:
            dm.addAction(f"d{sides}", lambda *a, n=sides: self.roll_dice(n))
        dm.addSeparator()
        dm.addAction("Advantage (2d20)", lambda *a: self.roll_dice(20, 2))
        dm.addAction("Custom roll... (like 5d20+3)", self.custom_roll)
        ddm = pm.addMenu("\U0001F3B2 Game night")
        if self.dnd_init["order"]:
            ddm.addAction(f"Next turn (now: {self.dnd_turn_name()})", self.dnd_next_turn)
        ddm.addAction("\U0001F4DC Session notes (pop out)", lambda *a: self.open_dnd_notes())
        ddm.addAction("My games, notes and initiative...", lambda *a: self.open_customize(4))

        om = menu.addMenu("\U0001F457 Outfit")
        for key, label in ACC_MENU:
            self.add_toggle(om, label, self.acc_mode == key,
                            lambda v, k=key: self.set_outfit(k))
        om.addSeparator()
        self.add_toggle(om, "Style: 3D (rendered)", self.outfit_style == "3d",
                        lambda v: self.set_outfit_style("3d"))
        self.add_toggle(om, "Style: drawn (flat)", self.outfit_style == "drawn",
                        lambda v: self.set_outfit_style("drawn"))
        menu.addSeparator()

        sm = menu.addMenu("\u2699\uFE0F Settings")
        bh = sm.addMenu("What she does")
        self.add_toggle(bh, "Wander around", self.wander, self.set_wander)
        self.add_toggle(bh, "Follow my mouse sometimes", self.follow_enabled, self.set_follow)
        win_label = "Hang out with my windows"
        if not HAS_WINLIST:
            win_label += " (needs setup)"
        self.add_toggle(bh, win_label, self.windows_enabled, self.set_windows)
        self.add_toggle(bh, "Fall when I drop her", self.gravity_enabled, self.set_gravity)
        bh.addSeparator()
        self.add_toggle(bh, "Sing along to music", self.sing_enabled, self.set_sing)
        self.add_toggle(bh, "Dance to music", self.dance_enabled, self.set_dance)
        self.add_toggle(bh, "React to my apps", self.react_enabled, self.set_react)
        self.add_toggle(bh, "React to Steam", self.steam_enabled, self.set_steam)
        self.add_toggle(bh, "Stream mode when OBS is open", self.stream_enabled, self.set_stream_auto)
        bh.addSeparator()
        self.add_toggle(bh, "Welcome-back greeting", self.welcome_enabled, self.set_welcome)
        self.add_toggle(bh, "Eye-rest nudges", self.eye_enabled, self.set_eye)

        fm = sm.addMenu("Fun stuff she does on her own")
        for key, label in [("bubbles", "Blowing bubbles"), ("crystal", "Crystal ball"),
                           ("teleport", "Teleporting"),
                           ("cursor", "Playing with the cursor"), ("flowers", "Picking flowers"),
                           ("cuddle", "Night cuddles"), ("typing", "Typing along with you"),
                           ("camera", "Camera when you take a screenshot"),
                           ("weather_report", "Weather reports (%s)" % ((self.place or {}).get("name") or "set your city first")),
                           ("weather_react", "Reacting to the weather")]:
            self.add_toggle(fm, label, self.fun[key],
                            lambda v, k=key: self.fun.__setitem__(k, v))
        self.add_toggle(fm, "Tarot card readings", self.tarot_enabled,
                        lambda v: setattr(self, "tarot_enabled", v))
        self.add_toggle(fm, "Snack time", self.snacks_enabled,
                        lambda v: setattr(self, "snacks_enabled", v))
        self.add_toggle(fm, "Sand castles", self.castles_enabled,
                        lambda v: setattr(self, "castles_enabled", v))

        bm = sm.addMenu("Nap bed")
        for key, name in [("random", "Surprise me (random)")] + list(self.BED_NAMES.items()) + [("none", "No bed (doze standing)")]:
            self.add_toggle(bm, name, self.bed_choice == key,
                            lambda v, k=key: self.set_bed_choice(k))

        vm = sm.addMenu("Voice")
        if self.ears is not None and dv.HAS_VOICE:
            self.add_toggle(vm, "Always listen for \"Hey Digi\"", self.listen_always,
                            self.set_listen_always)
        else:
            vm.addAction("Needs setup (" + INSTALL_HINT.rstrip("~") + ")", self.voice_help)
        vm.addAction("What can I say?", self.voice_help)
        if self.ears is not None and dv.HAS_VOICE:
            mm = vm.addMenu("Which microphone?")
            mics = dv.list_microphones()
            if IS_WIN:
                mics = []
                mm.addAction("Windows default mic").setEnabled(False)
                mm.addAction("(change it in Windows Sound settings)").setEnabled(False)
            else:
                self.add_toggle(mm, DEFAULT_MIC, self.ears.mic_uid is None,
                                lambda v: self.pick_mic(None, DEFAULT_MIC))
            for dev, uid, name in mics:
                self.add_toggle(mm, name, self.ears.mic_uid == uid,
                                lambda v, u=uid, n=name: self.pick_mic(u, n))
            if not mics and not IS_WIN:
                mm.addAction("(no microphones found)").setEnabled(False)
        vm.addAction("Check my ears", self.check_ears)
        sm.addSeparator()
        self.add_toggle(sm, "Start when I log in", autostart_enabled(), self.set_autostart)

        # every "show me now" tool in one place
        tm = menu.addMenu("\U0001F9EA Try it now")
        tm.addAction("Sit on a window", self.sit_now)
        tm.addAction("Play peekaboo", self.peek_now)
        if time.time() < self.nap_until:
            tm.addAction("Wake her up", self.wake_up)
        else:
            tm2 = tm.addMenu("Take a nap (30 sec)")
            tm2.addAction("Standing up (no bed)", lambda *a: self.test_nap("none"))
            for key, name in self.BED_NAMES.items():
                act = tm2.addAction(name, lambda *a, k=key: self.test_nap(k))
                act.setEnabled(("sleep_" + key) in self.frames)
        tm.addAction("Stretch", self.test_stretch)
        for label, fn in [("Pull a tarot card", lambda *a: self.start_activity("tarot")),
                          ("Snack time", lambda *a: self.start_activity("snack")),
                          ("Build a sand castle", lambda *a: self.start_activity("castle")),
                          ("Blow bubbles", lambda *a: self.start_activity("bubbles")),
                          ("Crystal ball", lambda *a: self.start_activity("crystal")),
                          ("Teleport", self.start_teleport),
                          ("Play with the cursor", lambda *a: self.start_activity("cursor")),
                          ("Pick flowers", lambda *a: self.start_activity("flowers")),
                          ("Night cuddles", lambda *a: self.start_activity("cuddle")),
                          ("Typing along", lambda *a: self.start_activity("typing")),
                          ("Take a photo", self.take_photo),
                          ("Get shy", self.get_shy)]:
            tm.addAction(label, fn)
        wm = tm.addMenu("Weather")
        for label, fn in [("Weather report now", lambda *a: self.tell_weather(True)),
                          ("Cold", lambda *a: self.weather_react("cold")),
                          ("Hot", lambda *a: self.weather_react("hot")),
                          ("Rain", lambda *a: self.weather_react("rain")),
                          ("Thunder", lambda *a: self.weather_react("thunder"))]:
            wm.addAction(label, fn)
        tm.addSeparator()
        tm.addAction("The hello tour (first-time intro)", self.start_intro)
        tm.addAction("Meditation invite", self.invite_meditation)
        tm.addAction("A test reminder", lambda: self.remind("Time for dinner!"))
        tm.addAction("Steam status", self.show_steam_status)

        menu.addSeparator()
        if getattr(self, "update_info", None):
            menu.addAction("\u2728 Update Digi (new version!)", self.do_update)
        else:
            menu.addAction("Check for updates", lambda *a: self.check_updates(manual=True))
        menu.addAction("Quit", QApplication.quit)
        self.run_menu(menu, e.globalPos())

    def run_menu(self, menu, pos):
        """Open one of her menus. She holds still (and quiet) while it's open, so it doesn't
        get away from you or close on you while you're looking through it."""
        self.menu_open = True
        self.walking = False
        opened = time.time()
        try:
            menu.exec(pos)
        finally:
            self.menu_open = False
            print("menu: open %.1f s" % (time.time() - opened), file=sys.stderr, flush=True)
            self.idle_cd = max(self.idle_cd, 250)      # and a little pause before she wanders off

    # ---------- water ----------
    def load_water(self):
        data = {"date": "", "count": 0, "goal": WATER_GOAL}
        try:
            with open(WATER_FILE, "r") as f:
                data.update(json.load(f))
        except Exception:
            pass
        return data

    def save_water(self):
        try:
            with open(WATER_FILE, "w") as f:
                json.dump(self.water, f)
        except Exception:
            pass

    def water_today(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.water.get("date") != today:
            self.water["date"] = today
            self.water["count"] = 0
            self.save_water()
        return self.water["count"]

    def drink(self):
        self.water_today()
        self.water["count"] += 1
        self.save_water()
        c, goal = self.water["count"], self.water["goal"]
        if self.reminder_active and "water" in self.last_reminder.lower():
            self.dismiss_reminder()
        if c == goal:
            self.say(f"You hit your water goal! {c}/{goal}! \u2728", 3500)
            self.happy = 60
            self.jump = 20
            for _ in range(8):
                self.hearts.append([random.randint(40, 180), random.randint(70, 110), 0, "\u2665"])
        else:
            self.say(f"{random.choice(DRINK_LINES)} ({c}/{goal})", 2200)
            self.happy = 20
            self.hearts.append([random.randint(80, 140), 90, 0, "\u2665"])

    def undrink(self):
        self.water_today()
        self.water["count"] = max(0, self.water["count"] - 1)
        self.save_water()
        self.say(f"Okay! ({self.water['count']}/{self.water['goal']})", 1800)

    def set_water_goal(self):
        n, ok = QInputDialog.getInt(self, "Water goal", "Glasses per day:",
                                    self.water["goal"], 1, 30)
        if ok:
            self.water["goal"] = n
            self.save_water()
            self.say(f"New goal: {n} a day!", 2000)

    # ---------- dice ----------
    def roll_dice(self, sides, count=1, mod=0):
        if self.dice:
            return
        self.roll_spec = (count, sides, mod)
        results = [random.randint(1, sides) for _ in range(count)]
        self.roll_results = results
        me = self.px + 110
        room_right = self.area.right() - me > me - self.area.left()
        d = 1 if room_right else -1
        floor = self.py + 228 - Die.SIZE
        floor = min(floor, self.area.bottom() - Die.SIZE)
        self.dice = []
        for i, r in enumerate(results[:10]):       # throw up to 10 real dice
            self.dice.append(Die(self.area, me + d * 55 - Die.SIZE / 2,
                                 self.py + 120, d * random.uniform(5, 11),
                                 -random.uniform(7, 12),
                                 floor - random.randint(0, 6), sides, r))
        self.dice_done_at = None
        self.happy = 12          # arms up: the throw!
        self.say("Here goes~!" if count == 1 else f"Rolling {count}d{sides}!", 1500)

    def custom_roll(self):
        text, ok = QInputDialog.getText(self, "Roll dice",
                                        "What should I roll? (like 5d20, 2d6+3, d100)",
                                        text=self.last_custom)
        if not ok:
            return
        spec = parse_roll(text)
        if not spec:
            self.say("Hmm, try something like 5d20 or 2d6+3!", 3000)
            return
        self.last_custom = text.strip()
        self.roll_dice(spec[1], spec[0], spec[2])

    def update_dice(self):
        for d in self.dice:
            d.step()
        if self.dice_done_at is None:
            if all(d.settled for d in self.dice):
                self.dice_done_at = self.t
                self.announce_roll()
        elif self.t - self.dice_done_at > 120:     # tidy up after ~5 s
            for d in self.dice:
                d.close()
            self.dice = []

    def announce_roll(self):
        count, sides, mod = self.roll_spec
        rs = self.roll_results
        kind, self.roll_kind = self.roll_kind, None
        if kind in ("advantage", "disadvantage") and len(rs) == 2:
            keep = max(rs) if kind == "advantage" else min(rs)
            label = "Advantage" if kind == "advantage" else "Disadvantage"
            extra = " \u2728 NAT 20!!" if keep == 20 else " \U0001F480" if keep == 1 else "!"
            self.say(f"{label}: {rs[0]} & {rs[1]} \u2192 {keep}{extra}", 6000)
            self.happy = 60 if keep == 20 else 15
            return
        total = sum(rs) + mod
        modtxt = f" {'+' if mod > 0 else '-'} {abs(mod)}" if mod else ""
        name = f"{count}d{sides}{modtxt.replace(' ', '')}" if count > 1 or mod else f"d{sides}"
        if count == 1:
            text = f"{name}: {rs[0]}" + (f"{modtxt} = {total}" if mod else "!")
        elif count <= 10:
            text = f"{name}: {' + '.join(str(r) for r in rs)}{modtxt} = {total}"
        else:
            text = f"{name}: {total}!  (highest {max(rs)}, lowest {min(rs)})"
        nat20 = sides == 20 and 20 in rs
        nat1 = sides == 20 and 1 in rs
        if nat20 and count == 1:
            text = "NAT 20!!! \u2728 " + text
        elif nat20:
            text = f"{rs.count(20)}x NAT 20! \u2728 " + text
        elif nat1 and count == 1:
            text = "Nat 1... oh no \U0001F480 " + text
        self.say(text, 6000)
        if nat20:
            self.happy = 60
            self.jump = 20
            for _ in range(10):
                self.hearts.append([random.randint(30, 190), random.randint(60, 120), 0,
                                    random.choice(["\u2665", "\u2605"])])
        elif nat1 and count == 1:
            self.surprised = True
            QTimer.singleShot(1200, lambda: setattr(self, "surprised", False))
        else:
            self.happy = 15

    # ---------- ball ----------
    def toss_ball(self):
        if self.ball:
            return
        bx = self.x() + (160 if self.x() < self.area.center().x() else 20)
        self.ball = Ball(self.area, bx, self.y() + 60)
        self.ball_until = time.time() + 45
        self.kicks = 0
        self.say("Ball!! \u2665", 1500)
        self.happy = 0

    def end_ball(self):
        if self.ball:
            self.ball.close()
            self.ball = None
            if not self.reminder_active:
                self.say("That was fun!", 2000)
            self.happy = 20

    def do_chase(self):
        b = self.ball
        me = self.px + 110
        side = 1 if b.cx() >= me else -1
        tx = b.cx() - side * 45 - 110
        ty = (b.y_ + Ball.SIZE) - 228
        gx, gy = self.clamp_pos(tx, ty)
        self.glide(gx, gy, 5.5)
        close_x = abs(b.cx() - me) < 75
        close_y = abs((b.y_ + Ball.SIZE / 2) - (self.py + 205)) < 70
        if close_x and close_y and self.kick_cd == 0 and not b.held:
            b.kick(side)
            self.kick_cd = 18
            self.kicks += 1
            if self.kicks % 2 == 1 and not self.reminder_active:
                self.say(random.choice(KICK_LINES), 1000)

    # ---------- gravity ----------
    def start_fall(self):
        self.falling = True
        self.fall_v = 0.0
        self.surprised = True
        floor = self.area.bottom() - 230
        self.fall_window = None
        w = self.get_front_window() if (self.windows_enabled and HAS_WINLIST) else None
        if w is not None:
            perch_y = w.top() - 221
            me = self.px + 110
            if w.left() < me < w.right() and self.py <= perch_y and self.can_perch(w):
                floor = perch_y
                self.fall_window = w
        self.fall_floor = floor
        if not self.reminder_active:
            self.say("Wheee!", 1200)

    def update_fall(self):
        self.fall_v = min(self.fall_v + 1.3, 28)
        self.py += self.fall_v
        if self.py >= self.fall_floor:
            self.py = float(self.fall_floor)
            if self.fall_v > 12:
                self.fall_v = -self.fall_v * 0.32     # little bounce
                self.swing_v += random.choice([-6, 6])
            else:
                self.falling = False
                self.surprised = False
                self.happy = 25
                if not self.reminder_active:
                    self.say(random.choice(["Ta-da!", "Stuck the landing!", "Oof!", "I'm okay!"]), 1500)
                if self.fall_window is not None:
                    self.cur_window = self.fall_window
                    self.set_mode("perch", random.uniform(15, 30))
        self.move(int(self.px), int(self.py))

    def set_gravity(self, value):
        self.gravity_enabled = value

    # ---------- stream mode ----------
    def check_obs(self):
        if HELPER:
            return W is not None and W.obs_running()
        try:
            r = subprocess.run(["pgrep", "-f", "OBS.app/Contents/MacOS"],
                               capture_output=True, timeout=3)
            return r.returncode == 0
        except Exception:
            return False

    def update_stream(self):
        was = self.streaming
        self.obs_open = self.check_obs()
        self.streaming = (self.stream_manual or self.movie or self.gaming or self.dnd_mode
                          or (self.stream_enabled and self.obs_open))
        if self.streaming and not was:
            if self.movie:
                self.say("Movie time! \U0001F37F I'll be quiet~", 3000)
            elif self.gaming:
                self.say(random.choice(GAMING_START), 3000)
            elif self.dnd_mode:
                self.say(random.choice(DND_MODE_START), 3000)
            else:
                self.say("Ooh, are we live? I'll sit quietly over here~", 3000)
            self.end_ball()
        elif was and not self.streaming:
            self.say("Great stream! \u2665", 2500)
            self.happy = 30

    def set_stream_manual(self, value):
        self.stream_manual = value
        self.update_stream()

    def set_movie(self, value):
        was = self.movie
        self.movie = value
        if was and not value:
            # the movie's over (stream mode may still be on)
            self.streaming = False
            self.update_stream()
            if not self.streaming:
                self.say(random.choice(["That was a good movie!", "Popcorn's all gone~ \U0001F37F",
                                        "Again! Again!"]), 2500)
                self.happy = 30
            return
        self.update_stream()

    def set_gaming(self, value):
        was = self.gaming
        self.gaming = value
        if was and not value:
            self.streaming = False
            self.update_stream()
            if not self.streaming:
                self.say(random.choice(GAMING_END), 2500)
                self.happy = 30
            return
        self.gaming_cheer = time.time() + random.uniform(120, 300)
        self.update_stream()

    def set_dnd_mode(self, value):
        was = self.dnd_mode
        self.dnd_mode = value
        if was and not value:
            self.streaming = False
            self.update_stream()
            if not self.streaming:
                self.say(random.choice(DND_MODE_END), 2500)
                self.happy = 30
            return
        self.dnd_mode_next = time.time() + random.uniform(10, 16)    # first roll soon after she sits
        if self.streaming and not was:          # switched over from another mode: say hi to D&D anyway
            self.say(random.choice(DND_MODE_START), 3000)
        self.update_stream()

    def check_dnd_mode(self):
        """D&D mode: every minute or so she narrates a bit of her adventure and rolls a d20."""
        if not (self.dnd_mode and self.corner_settled()) or time.time() < self.dnd_mode_next:
            return
        if self.msg or self.reminder_active or self.dice:
            return
        self.say(random.choice(SPELLS + DND_MODE_LINES), 2600)
        QTimer.singleShot(1800, lambda: self.roll_dice(20) if self.dnd_mode else None)
        self.dnd_mode_next = time.time() + random.uniform(45, 90)

    # ----- modes: one row of round buttons to pick how she hangs out -----
    def current_mode(self):
        if self.gaming:
            return "gaming"
        if self.dnd_mode:
            return "dnd"
        if self.movie:
            return "movie"
        if self.stream_manual:
            return "stream"
        if self.game_mode:
            return "cheer"
        return "off"

    # ----- rock, paper, scissors -----
    def play_rps(self):
        self.rps_game = [0, 0]
        self.walking = False
        self.say("Rock, paper, scissors! Pick one~ \u270A\u270B\u270C\ufe0f", 6000)
        self.show_choices(RPS_BUTTONS, self.rps_pick, big=True)

    def rps_pick(self, you):
        if you == "close":
            g = self.rps_game
            if g[0] or g[1]:
                end = ("You win the game!" if g[0] > g[1] else "I win the game! \u2728" if g[1] > g[0]
                       else "It's a draw!")
                self.say(f"Good game! {end} (You {g[0]} \u00b7 Digi {g[1]})", 4000)
            else:
                self.say("Okay, maybe later~", 2000)
            return
        her = random.choice(list(RPS_BEATS))
        self.rps_busy = True                 # she holds still for the countdown
        self.walking = False
        steps = ["Rock...", "Paper...", "Scissors...", "Shoot!"]
        for i, word in enumerate(steps):
            QTimer.singleShot(420 * i, lambda w=word: self.say(w, 600))
        QTimer.singleShot(420 * len(steps), lambda: self.rps_reveal(you, her))

    def rps_reveal(self, you, her):
        self.rps_busy = False
        vs = f"{RPS_EMOJI[you]} vs {RPS_EMOJI[her]}"
        if you == her:
            self.rps["tie"] += 1
            line = random.choice(RPS_TIE)
            self.boop_until = time.time() + 1.4          # a surprised little jump
        elif RPS_BEATS[her] == you:
            self.rps["digi"] += 1
            self.rps_game[1] += 1
            line = random.choice(RPS_WIN)
            self.happy = 40
            self.jump = 20
        else:
            self.rps["you"] += 1
            self.rps_game[0] += 1
            line = random.choice(RPS_LOSE)
            self.shy_until = time.time() + 2.2           # pouty and shy
        g = self.rps_game
        self.say(f"{vs}  {line}\nYou {g[0]} \u00b7 Digi {g[1]}  (\u2715 to stop)", 45000)
        self.save_custom()
        self.show_choices(RPS_BUTTONS, self.rps_pick, big=True)    # ready for the next round

    # ----- trivia -----
    def play_trivia(self):
        self.walking = False
        cats = [c for c in TRIVIA_CATS if c[1] != "mine" or self.trivia_mine]
        self.say("Trivia time! Pick a category~ \U0001F9E0", 45000)
        self.show_choices(cats, self.trivia_pick_cat, big=True)

    def trivia_pool(self, cat):
        if cat == "mine":
            return [(t["q"], t["a"], *t["wrong"]) for t in self.trivia_mine]
        if cat == "mix":
            return [q for qs in TRIVIA.values() for q in qs]
        return list(TRIVIA.get(cat, []))

    def trivia_pick_cat(self, cat):
        if cat == "close":
            self.say("Okay, another time~", 2000)
            return
        pool = self.trivia_pool(cat)
        if not pool:
            self.say("No questions there yet! Add some in Customize \u2192 Lists~", 3500)
            return
        fresh = [q for q in pool if q[0] not in self.trivia_seen]    # not asked lately first
        old = [q for q in pool if q[0] in self.trivia_seen]
        random.shuffle(fresh)
        random.shuffle(old)
        if len(fresh) < min(TRIVIA_ROUND, len(pool)):     # running out: start a new lap after this
            self.trivia_seen -= {q[0] for q in pool}
        qs = (fresh + old)[:TRIVIA_ROUND]
        self.trivia = {"cat": cat, "qs": qs, "i": 0, "score": 0, "streak": 0}
        self.trivia_ask()

    def trivia_ask(self):
        t = self.trivia
        if not t:
            return
        q = t["qs"][t["i"]]
        self.trivia_seen.add(q[0])
        answers = [q[1]] + [a for a in q[2:5] if a]
        random.shuffle(answers)
        t["answers"] = answers
        buttons = [(a.replace("&", "&&"), str(k)) for k, a in enumerate(answers)] + [("\u2715", "close")]
        self.say(f"Q{t['i'] + 1}/{len(t['qs'])}: {q[0]}", 120000)
        self.show_choices(buttons, self.trivia_answer, timeout=120)

    def trivia_answer(self, key):
        t = self.trivia
        if not t:
            return
        if key == "close":
            done = t["i"]
            self.trivia = None
            self.say(f"Okay! You got {t['score']}/{done} \u2665" if done else "Okay, another time~", 3000)
            return
        q = t["qs"][t["i"]]
        right = t["answers"][int(key)] == q[1]
        fact = q[5] if len(q) > 5 else ""
        if right:
            t["score"] += 1
            t["streak"] += 1
            line = random.choice(TRIVIA_RIGHT)
            if t["streak"] >= 3:
                line = f"{t['streak']} in a row?! \U0001F525"
            self.happy = 40
            self.jump = 20
        else:
            t["streak"] = 0
            line = f"{random.choice(TRIVIA_WRONG)} It's {q[1]}."
            self.boop_until = time.time() + 1.2
        self.say(line + (f" {fact}" if fact else ""), 3200 if fact else 2400)
        t["i"] += 1
        self.trivia_busy = True
        QTimer.singleShot(3400 if fact else 2600, self.trivia_next)

    def trivia_next(self):
        self.trivia_busy = False
        t = self.trivia
        if not t:
            return
        if t["i"] < len(t["qs"]):
            self.trivia_ask()
            return
        n, score, cat = len(t["qs"]), t["score"], t["cat"]
        self.trivia = None
        if score == n:
            line = "Perfect score!! \U0001F3C6"
        elif score >= n * 0.7:
            line = "Amazing! \u2728"
        elif score >= n * 0.4:
            line = "Nice job!"
        else:
            line = "Good try~ we'll study together! \U0001F4DA"
        best = self.trivia_best.get(cat)
        if n == TRIVIA_ROUND and (best is None or score > best):
            if best is not None:
                line += f" New best for {TRIVIA_NAMES[cat]}!"
            self.trivia_best[cat] = score
            self.save_custom()
        elif best is not None:
            line += f" (Your best: {best}/{TRIVIA_ROUND})"
        self.say(f"You got {score}/{n}! {line}", 5000)
        if score >= n * 0.7:
            self.happy = 50
            self.jump = 24

    def show_modes(self):
        self.show_choices(MODE_BUTTONS, self.pick_mode, active=self.current_mode(), big=True)

    def pick_mode(self, key):
        if key == "close" or key == self.current_mode():
            return
        # only one mode at a time: switch the others off first (quietly)
        if self.gaming and key != "gaming":
            self.gaming = False
        if self.dnd_mode and key != "dnd":
            self.dnd_mode = False
        if self.movie and key != "movie":
            self.movie = False
        if self.stream_manual and key != "stream":
            self.stream_manual = False
        if self.game_mode and key != "cheer":
            self.set_game_mode(False)
        if key == "gaming":
            self.set_gaming(True)
        elif key == "dnd":
            self.set_dnd_mode(True)
        elif key == "movie":
            self.set_movie(True)
        elif key == "stream":
            self.set_stream_manual(True)
        elif key == "cheer":
            self.set_game_mode(True)
            self.update_stream()
            self.say("I'll cheer you on while you play! \U0001F4E3", 3000)
        else:
            self.update_stream()
            if not self.streaming:
                self.say("Back to hanging out~", 2200)

    def corner_settled(self):
        """She's made it to her corner spot (movie, video game or D&D mode)."""
        if not (self.movie or self.gaming or self.dnd_mode) or self.dragging:
            return False
        tx = self.area.right() - 200
        ty = self.area.bottom() - 230
        return abs(self.px - tx) <= 3 and abs(self.py - ty) <= 3

    def movie_settled(self):
        """She's made it to her movie spot."""
        if not self.movie or self.dragging:
            return False
        tx = self.area.right() - 200
        ty = self.area.bottom() - 230
        return abs(self.px - tx) <= 3 and abs(self.py - ty) <= 3

    def draw_gamepad(self, p):
        """A little lilac controller on her lap, its buttons lighting up as she plays."""
        x0, y0 = 88, 200
        p.save()
        p.setPen(QPen(QColor("#4b3f7a"), 1.4))
        p.setBrush(QBrush(QColor("#c9bdf0")))
        p.drawEllipse(QRectF(x0 - 4, y0 + 2, 16, 18))          # grips
        p.drawEllipse(QRectF(x0 + 32, y0 + 2, 16, 18))
        p.drawRoundedRect(QRectF(x0, y0, 44, 16), 7, 7)       # body
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#4b3f7a")))
        p.drawRect(QRectF(x0 + 6, y0 + 7, 9, 3))              # d-pad
        p.drawRect(QRectF(x0 + 9, y0 + 4, 3, 9))
        cols = ("#f7a8c8", "#8fdcc3", "#ffd970", "#8cc8f2")
        lit = (self.t // 3) % 4
        for k, (dx, dy) in enumerate(((36, 5), (40, 9), (32, 9), (36, 13))):
            c = QColor(cols[k])
            if k == lit:
                c = c.lighter(135)
            p.setBrush(QBrush(c))
            r = 2.6 if k == lit else 2.2
            p.drawEllipse(QPointF(x0 + dx, y0 + dy - 1), r, r)
        p.restore()

    def draw_popcorn(self, p):
        """A striped popcorn bucket on her lap, and a piece flying up to her mouth now and then."""
        x0, y0, w, h = 93, 196, 34, 32
        bucket = QPolygonF([QPointF(x0, y0), QPointF(x0 + w, y0),
                            QPointF(x0 + w - 5, y0 + h), QPointF(x0 + 5, y0 + h)])
        # popcorn heaped on top
        p.setPen(QPen(QColor("#7a5a2e"), 1.2))
        for i, (dx, dy, r) in enumerate(((5, -2, 6), (13, -6, 7), (22, -4, 6), (29, -1, 5), (16, 0, 6),
                                         (9, 1, 5), (25, 2, 5))):
            p.setBrush(QBrush(QColor("#fff6d6" if i % 3 else "#ffe9a8")))
            p.drawEllipse(QPointF(x0 + dx, y0 + dy), r, r * 0.85)
        p.save()
        p.setClipping(True)
        p.setClipRegion(QRegion(bucket.toPolygon()))
        p.setPen(Qt.NoPen)
        for i in range(5):
            p.setBrush(QBrush(QColor("#e8383f") if i % 2 == 0 else QColor("white")))
            p.drawRect(QRectF(x0 + i * w / 5, y0, w / 5 + 0.5, h))
        p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(OUTLINE, 2))
        p.drawPolygon(bucket)
        # a piece of popcorn hops up to her mouth every couple of seconds
        ph = self.t % 50
        if ph < 16:
            k = ph / 16.0
            px = 104 + 6 * k
            py = 192 - 46 * k + 40 * k * k
            p.setPen(QPen(QColor("#7a5a2e"), 1))
            p.setBrush(QBrush(QColor("#fff6d6")))
            p.drawEllipse(QPointF(px, py - 30 * math.sin(math.pi * k)), 4, 3.5)
        elif ph < 34 and (self.t // 50) % 3 == 0:
            p.setFont(QFont("Helvetica", 9))
            p.setPen(QPen(QColor(120, 100, 160, 200)))
            p.drawText(QPointF(132, 160 - (ph - 16) * 0.6), "munch")

    def set_stream_auto(self, value):
        self.stream_enabled = value
        self.update_stream()

    def do_stream_corner(self):
        tx = self.area.right() - 200
        ty = self.area.bottom() - 230
        if abs(self.px - tx) > 2 or abs(self.py - ty) > 2:
            self.glide(tx, ty, 4.0)

    # ---------- voice ----------
    def launch_command(self):
        here = os.path.abspath(__file__)
        if IS_WIN:
            return [W.pythonw() if W else sys.executable, here]
        app = os.path.dirname(os.path.dirname(os.path.dirname(here)))
        if app.endswith(".app"):
            return ["/usr/bin/open", "-a", app]
        return [sys.executable, here]

    def voice_help(self):
        self.say("Hold-click me & talk! Try: hi Digi / what's 6 times 7 / "
                 "roll 5d20 / can you move?", 7000)

    def pick_mic(self, uid, name):
        self.ears.mic_uid = uid
        dv.save_mic_choice(uid)
        if self.ears.mode == "always":
            self.ears.start("always")
        self.say(f"\U0001F3A4 Now listening with: {name}", 3000)

    def check_ears(self):
        lines = []
        if dv is None:
            lines.append("\u274c My voice code didn't load.")
        elif not dv.HAS_VOICE:
            lines.append("\u274c Ears not installed. Run \"Install Digi's Ears.command\".")
        else:
            lines.append("\u2705 Ears installed.")
            if IS_LINUX:
                lines.append("Linux ears work offline (Vosk). If she can't hear you, check the mic")
                lines.append("in your sound settings, or pick one under Voice \u2192 Microphone.")
            if IS_WIN:
                lines.append("Windows needs two settings on (Settings \u2192 Privacy & security):")
                lines.append("   \u2022 Speech \u2192 Online speech recognition")
                lines.append("   \u2022 Microphone \u2192 Let desktop apps access your microphone")
            try:
                if not IS_MAC:
                    raise RuntimeError("skip")
                sp = int(dv.Speech.SFSpeechRecognizer.authorizationStatus())
                lines.append({0: "\u2753 Speech Recognition: not asked yet (hold-click me to ask)",
                              1: "\u274c Speech Recognition: DENIED (System Settings \u2192 Privacy & Security \u2192 Speech Recognition)",
                              2: "\u274c Speech Recognition: restricted on this Mac",
                              3: "\u2705 Speech Recognition: allowed"}.get(sp, f"Speech: {sp}"))
            except Exception as ex:
                if IS_MAC:
                    lines.append(f"Speech check failed: {ex}")
            try:
                if not IS_MAC:
                    raise RuntimeError("skip")
                mic = int(dv.AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
                    dv.AVFoundation.AVMediaTypeAudio))
                lines.append({0: "\u2753 Microphone: not asked yet",
                              1: "\u274c Microphone: restricted",
                              2: "\u274c Microphone: DENIED (System Settings \u2192 Privacy & Security \u2192 Microphone)",
                              3: "\u2705 Microphone: allowed"}.get(mic, f"Mic: {mic}"))
            except Exception as ex:
                if IS_MAC:
                    lines.append(f"Mic check failed: {ex}")
            try:
                rec = self.ears.recognizer
                lines.append("\u2705 Can listen offline" if rec.supportsOnDeviceRecognition()
                             else "\u26a0\ufe0f This Mac can't do offline speech for English yet")
                if not rec.isAvailable():
                    lines.append("\u274c Speech recognizer says it isn't available right now")
            except Exception:
                pass
            names = [m[2] for m in dv.list_microphones()]
            lines.append("\U0001F3A4 Using: " + (self.ears.mic_name if self.ears.buffers else
                         ("your pick" if self.ears.mic_uid else "Mac default")))
            lines.append("Mics I can see: " + (", ".join(names) or "none"))
            lines.append(f"Sound chunks heard last time: {self.ears.buffers}"
                         + ("  \u2190 0 means no sound came in" if self.ears.buffers == 0 else ""))
            lines.append("Last words: " + (f"\"{self.ears.last_heard}\"" if self.ears.last_heard else "(none)"))
            if self.ears.last_error:
                lines.append("Last problem: " + self.ears.last_error)
        box = QMessageBox()
        box.setWindowTitle("Digi's ears")
        box.setWindowFlags(box.windowFlags() | Qt.WindowStaysOnTopHint)
        box.setText("\n".join(lines))
        box.exec()

    def start_ptt(self):
        if not self.dragging or self.moved:
            return
        if not dv.HAS_VOICE:
            self.say("I need my ears first! " + INSTALL_HINT, 4000)
            return
        self.ptt = True
        self.surprised = False
        self.voice_text = ""
        self.ears.want_always = False
        self.ears.start("ptt")
        self.say("\U0001F3A4 I'm listening... (talk, then let go)", 20000)

    def mouseDoubleClickEvent(self, e):
        """Double-click: she listens until you stop talking. No holding needed."""
        if e.button() != Qt.LeftButton or self.ears is None:
            return
        self.ptt_timer.stop()
        self.dragging = False
        if not dv.HAS_VOICE:
            self.say("I need my ears first! " + INSTALL_HINT, 4000)
            return
        self.tap_talk = self.t
        self.voice_text = ""
        self.voice_changed = time.time()
        self.ears.want_always = False
        self.ears.start("ptt")
        self.say("\U0001F3A4 I'm listening! Just talk~", 20000)

    def end_tap_talk(self):
        self.tap_talk = 0
        self.ptt_waiting = self.t
        self.ears.finish_talking()

    def set_listen_always(self, value):
        self.listen_always = value
        self.ears.want_always = value and not self.streaming
        if value:
            self.ears.start("always")
            self.say('Say "Hey Digi" anytime~', 2500)
        else:
            self.ears.stop()
            self.say("Okay, ears off!", 1800)

    def on_ear_status(self, st):
        if HELPER and st in ("missing", "dictation", "mic-denied", "denied"):
            self.say({"missing": "I need my ears first! " + INSTALL_HINT,
                      "dictation": "Turn on my ears: Settings \u2192 Privacy & security \u2192 Speech \u2192 "
                                   "Online speech recognition!",
                      "mic-denied": "I can't use the mic~ Settings \u2192 Privacy & security \u2192 Microphone "
                                    "\u2192 let desktop apps use it!",
                      "denied": "I can't hear you~ Check Settings \u2192 Privacy & security \u2192 Speech."}[st], 7000)
            self.listen_always = False
            self.ptt_waiting = 0
            return
        if st == "missing":
            self.say("I need my ears first! " + INSTALL_HINT, 4000)
        elif st == "denied":
            self.say("I can't hear you~ Allow Speech & Mic for DigiPal in System Settings.", 6000)
            self.listen_always = False
        elif st == "mic-denied":
            self.say("I can't use the mic~ Allow DigiPal (or Python) in System Settings \u2192 Privacy & Security \u2192 Microphone.", 7000)
            self.listen_always = False
        elif st == "needs-fix":
            self.say("I need one more fix to use the mic: double-click 'Fix Digi's Mic' in Downloads!", 7000)
            self.ptt_waiting = 0
        elif st == "dictation":
            self.say("Turn on Dictation for me: System Settings \u2192 Keyboard \u2192 Dictation!", 7000)
            self.ears.stop(quiet=True)
            self.ptt_waiting = 0
        elif st.startswith("error"):
            print("ears error:", st, file=sys.stderr, flush=True)       # full details in digipal.log
            self.say("My ears glitched~ Try turning listening off and on again!", 5000)

    def on_heard(self, text, final):
        if final and not text.strip():
            text = self.voice_text          # Apple sometimes ends with a blank final
        self.voice_text = text
        self.voice_changed = time.time()
        if self.ptt or self.ptt_waiting or self.tap_talk:
            self.msg = "\U0001F3A4 " + text
            self.msg_ticks = 60
            if final and self.ptt_waiting:
                self.ptt_waiting = 0
                self.voice_handled = text
                self.handle_voice(dv.strip_wake(text)[1])
                self.resume_always()
        elif self.ears.mode == "always":
            had, rest = dv.strip_wake(text)
            if had or time.time() < self.attentive_until:
                self.msg = "\U0001F3A4 " + (rest or "...")
                self.msg_ticks = 60

    def voice_tick(self):
        now = time.time()
        # double-click talking: stop once you've gone quiet
        if self.tap_talk:
            ticks = self.t - self.tap_talk
            if (self.voice_text and now - self.voice_changed > 1.4) or ticks > 300 \
                    or (not self.voice_text and ticks > 175):
                self.end_tap_talk()
        # push-to-talk: if the final words never come, use what we have
        if self.ptt_waiting and self.t - self.ptt_waiting > 75:
            self.ptt_waiting = 0
            text = self.voice_text
            self.ears.stop(quiet=True)
            if text and text != self.voice_handled:
                self.voice_handled = text
                self.handle_voice(dv.strip_wake(text)[1])
            else:
                self.say("Hmm? I didn't hear anything~", 2000)
            self.resume_always()
            return
        # streaming pauses always-listening
        if self.listen_always:
            want = not self.streaming
            if self.ears.want_always != want:
                self.ears.want_always = want
                if want and self.ears.mode is None:
                    self.ears.start("always")
                elif not want and self.ears.mode == "always":
                    self.ears.stop(quiet=True)
        if self.ears.mode != "always":
            return
        text = self.voice_text
        quiet_for = now - self.voice_changed
        if text and quiet_for > 1.2 and text != self.voice_handled:
            had, rest = dv.strip_wake(text)
            attentive = now < self.attentive_until
            if had or attentive:
                self.voice_handled = text
                if not rest:
                    self.attentive_until = now + 6
                    self.say("Yes? \U0001F3A4", 6000)
                    self.happy = 10
                else:
                    self.attentive_until = 0
                    self.handle_voice(rest)
                self.voice_text = ""
                self.ears.start("always")       # fresh start for the next thing
            elif quiet_for > 4:
                self.voice_text = ""
                self.ears.start("always")       # forget random chatter
        elif now - self.ears.started_at > 50 and quiet_for > 2:
            self.voice_text = ""
            self.ears.start("always")           # Apple likes short sessions

    def resume_always(self):
        if self.listen_always and not self.streaming:
            self.ears.want_always = True
            QTimer.singleShot(400, lambda: self.ears.start("always")
                              if self.ears.mode is None else None)

    def handle_voice(self, text):
        action, info = dv.understand(text)
        if action == "hello":
            self.say(random.choice(["Hi hi! \u2665", "Hiii~!", "Hello! *waves*", "Hey you! \u2665"]), 2500)
            self.happy = 40
            self.jump = 15
            self.hearts.append([random.randint(80, 140), 90, 0, "\u2665"])
        elif action == "math":
            pretty, val = info
            self.say(f"{pretty} = {val}!", 4000)
            self.happy = 20
        elif action == "roll":
            count, sides, mod, kind = info
            self.roll_kind = kind
            self.roll_dice(sides, count, mod)
        elif action == "move":
            me = self.px + 110
            left = me > self.area.center().x()
            tx = self.area.left() + 20 if left else self.area.right() - 240
            ty = self.area.bottom() - 230
            self.shoo_target = (tx, ty)
            self.shoo_until = time.time() + 120
            self.set_mode("wander", 120)
            self.say("Okay! I'll hang out over here~", 2500)
        elif action == "come":
            self.shoo_until = 0
            self.come_here()
        elif action == "sleep":
            self.nap_now()
        elif action == "wake":
            self.wake_up()
        elif action == "water":
            self.drink()
        elif action == "ball":
            self.toss_ball()
        elif action == "bomb":
            self.throw_bomb()
        elif action == "time":
            now = datetime.now()
            self.say(f"It's {now.strftime('%-I:%M %p').lower()}!", 3000)
        elif action == "sit":
            self.sit_now()
        elif action == "dance":
            self.sing_until = time.time() + 12
        elif action == "love":
            self.say("Aww! \u2665\u2665\u2665", 2500)
            self.happy = 40
            for _ in range(4):
                self.hearts.append([random.randint(60, 160), random.randint(80, 110), 0, "\u2665"])
        else:
            self.say("Hmm? I didn't catch that~", 2500)

    # ---------- lots of little fun things ----------
    def pose_now(self):
        """A special pose that's playing right now, as (state, speed), or None."""
        if self.dragging or self.bed:
            return None
        now = time.time()
        a = self.activity
        for until, state, speed in ((self.scared_until, "scared", 3), (self.shy_until, "shy", 4),
                                    (self.camera_until, "camera", 6), (self.shiver_until, "shiver", 2),
                                    (self.boop_until, "surprised", 5), (self.umbrella_until, "umbrella", 5),
                                    (self.hot_until, "sleepy", 6)):
            if now < until and state in self.frames:
                return (state, speed)
        if a and self.floor_sit:
            if a["kind"] == "cuddle":
                st = "cuddle_" + a.get("prop", "teddy")
                if st in self.frames:
                    return (st, 6)
            if a["kind"] == "typing" and "typing" in self.frames:
                return ("typing", 2)
        return None

    def pick_idle_fun(self):
        """Pick something fun to do while idle. Returns True if she started something."""
        if (self.bed or self.streaming or self.focus_end or self.sleepy or self.reminder_active
                or self.med_end or self.intro_step >= 0):
            return False
        now = datetime.now()
        h = now.hour + now.minute / 60
        choices = []
        if self.tarot_enabled:
            choices += ["tarot"]
        if self.snacks_enabled:
            choices += ["snack"]
        if self.castles_enabled:
            choices += ["castle"]
        for key in ("bubbles", "crystal", "flowers", "cursor"):
            if self.fun[key]:
                choices.append(key)
        if self.fun["teleport"]:
            choices.append("teleport")
        if self.fun["cuddle"] and (h >= 21 or h < 0.5):
            choices += ["cuddle"] * 3
        w = self.weather_kind()
        if w and self.fun["weather_react"]:
            choices += ["weather"] * 3
        if not choices:
            return False
        pick = random.choice(choices)
        if pick == "teleport":
            self.start_teleport()
        elif pick == "weather":
            self.weather_react(w)
        else:
            self.start_activity(pick)
        return True

    def start_sitting_fun(self, a, now):
        kind = a["kind"]
        if kind == "crystal":
            x, y = self.item_spot(CrystalBall.W, CrystalBall.H)
            self.crystal = CrystalBall(x, y, self.tell_fortune)
            self.say("Let me look into my crystal ball... \U0001F52E", 2500)
            a["until"] = now + 25
            a["fortune_at"] = now + 3
        elif kind == "flowers":
            self.say(random.choice(["*picking flowers*", "Ooh, pretty ones~", "This one... and this one!"]), 2500)
            a["until"] = now + 28
            a["give_at"] = now + 3.5
        elif kind == "dnd":
            self.say(random.choice(["Time for a little solo adventure~", "The dungeon awaits!",
                                    "My turn! My turn!"]), 2200)
            a["until"] = now + 40
            a["next_roll"] = now + 2.5
        elif kind == "cuddle":
            a["prop"] = random.choice(["teddy", "teddy", "ball"])
            self.say("*cuddles Robo-Teddy* \u2665" if a["prop"] == "teddy" else "*hugs her squishy ball*", 3000)
            a["until"] = now + 40
        elif kind == "typing":
            self.say(random.choice(["I'll help you type! *tap tap*", "Work work~", "Typing buddies! \u2328\ufe0f"]), 2500)
            a["until"] = now + 600          # ends when you stop typing
            self.last_key_burst = now

    def showing_fun(self, a, now):
        kind = a["kind"]
        if kind == "bubbles":
            if self.t % 14 == 0 and len(self.soap) < 14 and now < a["until"] - 1:
                bx = self.x() + (140 if random.random() < 0.5 else 60)
                self.soap.append(SoapBubble(bx, self.y() + 95, self.bubble_popped))
        elif kind == "crystal":
            if a.get("fortune_at") and now > a["fortune_at"]:
                a["fortune_at"] = None
                self.tell_fortune()
        elif kind == "flowers":
            if a.get("give_at") and now > a["give_at"]:
                a["give_at"] = None
                x, y = self.item_spot(Bouquet.W, Bouquet.H)
                self.bouquet = Bouquet(x, y, self.flowers_taken)
                self.say("These are for you! \U0001F490", 4000)
                self.happy = 0
            if now > a["until"] - 0.3 and self.bouquet and not self.bouquet.taken and not a.get("kept"):
                a["kept"] = True
                self.say("I'll keep them, then~ *sniff sniff*", 2200)
        elif kind == "dnd":
            if a.get("next_roll") and now > a["next_roll"] and not self.dice:
                self.say(random.choice(SPELLS), 2200)
                QTimer.singleShot(1500, lambda: self.roll_dice(20) if self.activity else None)
                a["next_roll"] = now + random.uniform(12, 16)
        elif kind == "typing":
            if now - self.last_key_burst > 6:
                self.say(random.choice(["Phew, good work!", "All done typing?", "*stretches fingers*"]), 2000)
                self.end_activity()
        elif kind == "cursor":
            if now > a["until"]:
                self.say(random.choice(["Hehe, you win~", "That was fun! \u2665", "I almost had it!"]), 2000)

    def bubble_popped(self):
        if random.random() < 0.35 and not self.reminder_active:
            self.say(random.choice(["Pop!", "Hehe!", "Got one!", "Pop pop~"]), 900)

    def tell_fortune(self):
        self.say("Hmm... I see... " + random.choice(FORTUNES), 6000)
        self.happy = 0

    def flowers_taken(self):
        self.say("Yay! You like them? \u2665", 2500)
        self.happy = 40
        for _ in range(5):
            self.hearts.append([random.randint(60, 160), random.randint(80, 110), 0, "\u2665"])
        if self.activity:
            self.activity["until"] = time.time() + 2.5

    def chase_cursor(self):
        cp = QCursor.pos()
        tx, ty = cp.x() - 110, cp.y() - 175
        gx, gy = self.clamp_pos(tx, ty)
        dist = math.hypot(gx - self.px, gy - self.py)
        self.glide(gx, gy, min(9.0, max(2.0, dist * 0.12)))
        if self.swat_cd > 0:
            self.swat_cd -= 1
        elif dist < 25:
            self.jump = 12
            self.happy = 8
            self.swat_cd = 30
            if random.random() < 0.6:
                self.say(random.choice(["Gotcha!", "Nya!", "*swat swat*", "Mine!", "Pounce!"]), 900)

    def is_nose(self, pos):
        if self.bed or self.mode == "peek":
            return False
        dy = 33 if self.floor_sit else 0
        return math.hypot(pos.x() - self.pad_x - 110, pos.y() - self.pad_y - (118 + dy)) < 14

    def boop(self):
        self.boop_until = time.time() + 1.6
        self.say(random.choice(BOOP_LINES), 1800)
        self.hearts.append([random.randint(90, 130), 100, 0, "\u2665"])

    def get_shy(self):
        self.shy_until = time.time() + 5
        self.pat_times = []
        self.happy = 0
        self.say(random.choice(SHY_LINES), 3000)

    def take_photo(self):
        if self.bed or self.dragging:
            return
        self.camera_until = time.time() + 2.6
        self.say(random.choice(["Say cheese! \U0001F4F8", "*click!*", "Ooh, I'll take one too!"]), 2000)
        QTimer.singleShot(900, lambda: setattr(self, "flash", 8))

    # teleporting
    def start_teleport(self):
        if self.teleport is not None or self.bed or self.dragging or self.activity:
            return
        a = self.area
        tx = random.randint(a.left() + 20, max(a.left() + 20, a.right() - 240))
        ty = random.randint(a.top() + 60, max(a.top() + 60, a.bottom() - 230))
        self.teleport = {"t": 0, "to": (tx, ty)}
        self.say(random.choice(["Abracadabra~ \u2728", "*poof*", "Teleport!", "Now you see me~"]), 1500)

    def teleport_alpha(self):
        if self.teleport is None:
            return 1.0
        t = self.teleport["t"]
        return max(0.0, 1 - t / 10) if t < 10 else min(1.0, (t - 12) / 10)

    # weather
    def weather_loop(self):
        import urllib.request
        while True:
            pl = self.place
            if not pl:
                self.weather = None
                time.sleep(5)
                continue
            key = (pl["lat"], pl["lon"], self.units)
            url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
                   "&current=temperature_2m,apparent_temperature,weather_code"
                   "&temperature_unit=%s&timezone=auto") % (
                pl["lat"], pl["lon"], "celsius" if self.units == "C" else "fahrenheit")
            try:
                try:
                    with urllib.request.urlopen(url, timeout=15) as r:
                        cur = json.loads(r.read().decode())["current"]
                except Exception:
                    # some Mac Pythons are missing web certificates; the plain address works too
                    with urllib.request.urlopen(url.replace("https://", "http://"), timeout=15) as r:
                        cur = json.loads(r.read().decode())["current"]
                self.weather = {"temp": round(cur["temperature_2m"]),
                                "feels": round(cur["apparent_temperature"]),
                                "code": int(cur["weather_code"])}
            except Exception:
                pass
            # check again in 20 minutes (sooner if you pick a new city or units)
            for _ in range(240):
                time.sleep(5)
                p2 = self.place
                if not p2 or (p2["lat"], p2["lon"], self.units) != key:
                    break

    def weather_kind(self):
        w = self.weather
        if not w:
            return None
        if w["code"] in (95, 96, 99):
            return "thunder"
        if w["code"] in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
            return "rain"
        cold, hot = (COLD_C, HOT_C) if self.units == "C" else (COLD_F, HOT_F)
        if w["feels"] <= cold or w["code"] in (71, 73, 75, 77, 85, 86):
            return "cold"
        if w["feels"] >= hot:
            return "hot"
        return None

    def tell_weather(self, forced=False):
        w = self.weather
        if not w:
            if forced:
                self.say("Tell me your city first! Customize \u2192 Personal settings~" if not self.place
                         else "Hmm, I can't see the weather right now~", 3000)
            return
        words, icon = weather_words(w["code"])
        extra = ""
        kind = self.weather_kind()
        if kind == "cold":
            extra = " Bundle up!"
        elif kind == "hot":
            extra = " Stay cool & drink water!"
        elif kind == "rain":
            extra = " Grab an umbrella!"
        elif kind == "thunder":
            extra = " Stay inside, okay?"
        town = (self.place or {}).get("name", "").split(",")[0]
        self.say(f"{icon} It's {w['temp']}\u00b0{self.units} and {words}"
                 + (f" in {town}" if town else "") + f".{extra}", 7000)
        self.happy = 0

    def weather_react(self, kind):
        now = time.time()
        t = (self.weather or {}).get("temp")
        tt = f" {t}\u00b0{self.units}..." if t is not None else ""
        self.snow = bool(self.weather and self.weather["code"] in (71, 73, 75, 77, 85, 86))
        if kind == "cold":
            self.shiver_until = now + 6
            self.say(f"Brrr!{tt} So cold~ \U0001F976", 3000)
        elif kind == "hot":
            self.hot_until = now + 7
            self.say(f"So hot...{tt} \U0001F975", 3000)
        elif kind == "rain":
            self.umbrella_until = now + 15
            self.say("It's raining! Good thing I have my umbrella \u2602\ufe0f", 3000)
        elif kind == "thunder":
            self.scared_until = now + 5
            self.flash = 8
            self.say("Eek! Thunder!! \u26a1", 3000)
        self.happy = 0

    def screenshot_loop(self):
        was = False
        while True:
            try:
                if HELPER:
                    on = W is not None and W.screenshot_running()
                else:
                    r = subprocess.run(["pgrep", "-x", "screencaptureui"], capture_output=True, timeout=3)
                    on = r.returncode == 0
            except Exception:
                on = False
            if on and not was:
                self.snap_pending = True
            was = on
            time.sleep(0.8)

    def fun_tick(self):
        now = time.time()
        # bubbles float away
        for b_ in self.soap:
            b_.step()
        for b_ in [x for x in self.soap if x.finished() or x.y() < self.area.top() - 60]:
            b_.close()
            self.soap.remove(b_)
        if self.crystal:
            self.crystal.step()
        if self.bouquet:
            self.bouquet.step()
            if self.bouquet.taken > 25:
                self.bouquet.close()
                self.bouquet = None
        if self.flash > 0:
            self.flash -= 1
        # teleport: fade out, jump, fade in
        if self.teleport is not None:
            self.teleport["t"] += 1
            if self.teleport["t"] == 11:
                tx, ty = self.teleport["to"]
                self.px, self.py = float(tx), float(ty)
                self.move(int(tx), int(ty))
            if self.teleport["t"] >= 22:
                self.teleport = None
        # thunder now and then while she's scared
        if now < self.scared_until and random.random() < 0.02:
            self.flash = 6
        # you took a screenshot
        if self.snap_pending:
            self.snap_pending = False
            if self.fun["camera"]:
                self.take_photo()
        # typing along: check the keyboard about twice a second (no special permission needed)
        if (HAS_QUARTZ or (HELPER and W)) and self.t % 12 == 0 and self.fun["typing"]:
            try:
                if HELPER:
                    # Windows only says "something was touched": count it as typing when the
                    # mouse hasn't moved since last time
                    cur = QCursor.pos()
                    secs = W.seconds_since_input()
                    if cur != getattr(self, "_last_cursor", None):
                        secs = 999
                    self._last_cursor = cur
                else:
                    secs = Quartz.CGEventSourceSecondsSinceLastEventType(
                        Quartz.kCGEventSourceStateHIDSystemState, Quartz.kCGEventKeyDown)
            except Exception:
                secs = 999
            if secs < 0.8:
                self.key_streak += 1
                self.last_key_burst = now
            else:
                self.key_streak = 0
            if (self.key_streak == 4 and not self.activity and not self.bed and not self.streaming
                    and not self.med_end
                    and not self.dragging and random.random() < 0.5):
                self.start_activity("typing")
        # weather reports 3 times a day
        if self.t % 25 == 0 and self.fun["weather_report"]:
            key = datetime.now().strftime("%Y-%m-%d %H:%M")
            if key[-5:] in WEATHER_TIMES and key not in self.weather_told and not self.bed:
                self.weather_told.add(key)
                self.tell_weather()
                k = self.weather_kind()
                if k and self.fun["weather_react"]:
                    QTimer.singleShot(7500, lambda: self.weather_react(k))

    def draw_fun_effects(self, p, b):
        now = time.time()
        # rain around her umbrella
        if now < self.umbrella_until:
            p.setPen(QPen(QColor(110, 160, 230, 190), 2))
            for i in range(16):
                x = (i * 37 + self.t * 3) % 220
                y = (i * 53 + self.t * 9) % 240
                p.drawLine(QPointF(x, y), QPointF(x - 3, y + 10))
        # cold: snowflakes if it's snowy, plus a little "brr" breath puff
        if now < self.shiver_until:
            if self.snow:
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor(255, 255, 255, 230)))
                for i in range(14):
                    x = (i * 41 + math.sin(self.t / 12 + i) * 8) % 220
                    y = (i * 29 + self.t * 2) % 240
                    p.drawEllipse(QPointF(x, y), 2.5, 2.5)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(255, 255, 255, 150)))
            k = (self.t % 30) / 30.0
            p.drawEllipse(QPointF(128 + 14 * k, 120 + b - 6 * k), 4 + 6 * k, 3 + 4 * k)
        # hot: sweat drops
        if now < self.hot_until:
            p.setPen(QPen(QColor("#1b1b1b"), 1.2))
            p.setBrush(QBrush(QColor(120, 190, 255, 220)))
            for i, (x, y) in enumerate(((70, 74), (152, 80))):
                dy = (self.t * 0.6 + i * 9) % 18
                p.drawPolygon(QPolygonF([QPointF(x, y + b + dy - 6), QPointF(x - 4, y + b + dy + 3),
                                         QPointF(x + 4, y + b + dy + 3)]))
                p.drawEllipse(QPointF(x, y + b + dy + 3), 4, 4)
        # shy blush hearts
        if now < self.shy_until and self.t % 20 == 0:
            self.hearts.append([random.randint(70, 150), 95, 0, "\u2665"])
        # teleport sparkles
        if self.teleport is not None:
            t = self.teleport["t"]
            k = (t % 11) / 11.0
            p.setPen(QPen(QColor(255, 230, 120, int(255 * (1 - k))), 2.5))
            for i in range(10):
                a = math.radians(i * 36 + t * 8)
                r1, r2 = 20 + 60 * k, 30 + 70 * k
                p.drawLine(QPointF(110 + r1 * math.cos(a), 140 + r1 * math.sin(a)),
                           QPointF(110 + r2 * math.cos(a), 140 + r2 * math.sin(a)))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(255, 255, 255, int(160 * (1 - k)))))
            p.drawEllipse(QPointF(110, 140), 40 * (1 - k) + 5, 40 * (1 - k) + 5)
        # camera / lightning flash
        if self.flash > 0:
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(255, 255, 255, int(200 * self.flash / 8))))
            p.drawRect(QRectF(0, 0, 220, 240))

    # ---------- bomb ----------
    def throw_bomb(self):
        if self.bomb or self.bed:
            return
        me = self.px + 110
        d = 1 if self.area.right() - me > me - self.area.left() else -1
        floor = min(self.py + 228 - Bomb.SIZE, self.area.bottom() - Bomb.SIZE)
        self.bomb = Bomb(self.area, me + d * 40 - Bomb.SIZE / 2, self.py + 100,
                         d * random.uniform(7, 11), -random.uniform(9, 13), floor)
        self.happy = 12                        # arms up: the throw!
        self.say(random.choice(["Heads up~!", "Catch!", "Hehe, watch this!", "Fire in the hole~!"]), 1500)

    def update_bomb(self):
        self.bomb.step()
        if self.bomb.just_exploded:
            self.bomb.just_exploded = False
            self.surprised = True
            self.jump = 14
            QTimer.singleShot(700, self.bomb_giggle)
        if self.bomb.done:
            self.bomb.close()
            self.bomb = None

    def bomb_giggle(self):
        self.surprised = False
        self.happy = 40
        self.say(random.choice(["Hehehe~", "Oops! Tehehe~", "Teehee! \u2665", "Oopsie~ hehe",
                                "That was SO cool!", "...I didn't do it. Hehe"]), 2500)

    # ---------- tarot + snack breaks ----------
    def test_stretch(self):
        self.stretch_until = time.time() + 8
        self.say("Stretch time! Reach up high!", 3000)

    def start_activity(self, kind):
        if self.activity or self.bed or self.dragging:
            return
        self.end_activity(quiet=True)
        if self.sitting:
            self.sitting = False
        act = {"kind": kind, "phase": "going", "until": time.time() + 12}
        if kind in ("bubbles", "cursor"):
            # these happen right where she is
            act["spot"] = "here"
            act["phase"] = "showing"
            act["until"] = time.time() + (10 if kind == "bubbles" else 14)
            self.activity = act
            if kind == "bubbles":
                self.say(random.choice(["Bubble time~ \U0001FAE7", "Fuuu~", "Pop them if you can!"]), 2500)
            else:
                self.say(random.choice(["Ooh, what's that?! \U0001F440", "That cursor... must catch it!",
                                        "Nya~ gonna get you!"]), 2500)
            return
        w = self.get_front_window() if (self.windows_enabled and HAS_WINLIST) else None
        if (kind not in ("castle", "cuddle", "typing", "dnd") and w is not None
                and self.can_perch(w) and "sit" in self.frames
                and random.random() < 0.5):
            act["spot"] = "window"
            self.cur_window = w
            self.set_mode("perch", 60)
            self.want_sit = True
        else:
            act["spot"] = "floor"
            lo, hi = self.area.left() + 20, self.area.right() - 360
            if kind == "typing":           # sit down right below where she is
                tx = int(max(lo, min(self.px, max(lo, hi))))
            else:
                tx = random.randint(lo, max(lo, hi))
            act["target"] = (tx, self.area.bottom() - 230)
        self.activity = act

    def do_activity_move(self):
        a = self.activity
        if a["spot"] == "here":
            if a["kind"] == "cursor":
                self.chase_cursor()
            return
        if a["phase"] != "going":
            if a["spot"] == "window":
                self.do_perch()
            return
        if a["spot"] == "window":
            self.do_perch()
            if self.sitting:
                self.sit_until = time.time() + 40
                self.begin_activity()
        else:
            tx, ty = a["target"]
            if self.glide(tx, ty, 5.0):
                self.floor_sit = True
                self.begin_activity()
        if time.time() > a["until"] and a["phase"] == "going":
            self.begin_activity()           # couldn't get there, do it here

    def begin_activity(self):
        a = self.activity
        a["phase"] = "sitting"
        a["until"] = time.time() + 1.2
        a["step"] = 0

    def item_spot(self, w, h):
        """Beside her hand, on whichever side has room."""
        x = self.x() + 165
        if x + w > self.area.right():
            x = self.x() - w + 55
        y = self.y() + 228 - h - 6
        return x, y

    def activity_tick(self):
        if self.card:
            self.card.step()
        if self.snack:
            self.snack.step()
        if self.castle:
            self.castle.step()
            if self.castle.broken > 45:
                self.castle.close()
                self.castle = None
        a = self.activity
        if not a:
            return
        now = time.time()
        if self.dragging or self.bed:
            self.end_activity(quiet=True)
            return
        if a["phase"] == "sitting" and now > a["until"]:
            a["phase"] = "showing"
            if a["kind"] == "tarot":
                card = random.choice(TAROT)
                rev = random.random() < 0.3
                a["card"], a["rev"] = card, rev
                x, y = self.item_spot(TarotCard.W, TarotCard.H)
                self.card = TarotCard(x, y, card, rev, self.read_card)
                self.say("This is your card~ \U0001F52E", 2500)
                a["until"] = now + 25
                a["read_at"] = now + 2.2
            elif a["kind"] in ("crystal", "flowers", "dnd", "cuddle", "typing"):
                self.start_sitting_fun(a, now)
            elif a["kind"] == "castle":
                x = self.x() + 160 if self.x() + 300 < self.area.right() else self.x() - 70
                y = self.y() + 228 - SandCastle.H
                self.castle = SandCastle(x, y, self.castle_broken, self.castle_done)
                self.say(random.choice(["Sand castle time~!", "Watch this! \U0001F3D6\ufe0f",
                                        "I'm gonna build a castle!"]), 2500)
                a["until"] = now + 45
            else:
                emoji, name = random.choice(SNACKS)
                a["name"] = name
                x, y = self.item_spot(Snack.SIZE, Snack.SIZE)
                self.snack = Snack(x, y, emoji, self.bite)
                self.say(f"Want one? It's a {name}! \u2665", 4000)
                a["until"] = now + 30
            self.happy = 0
        elif a["phase"] == "showing":
            self.showing_fun(a, now)
            if a["kind"] == "tarot" and a.get("read_at") and now > a["read_at"]:
                a["read_at"] = None
                self.read_card()
            if now > a["until"]:
                if a["kind"] == "snack" and self.snack and not self.snack.bites:
                    self.say("Okay, more for me! *nom*", 2200)
                self.end_activity()

    def read_card(self):
        a = self.activity
        if not a or "card" not in a:
            return
        num, name, sym, up, down = a["card"]
        if a["rev"]:
            self.say(f"This is your card: {name} (reversed) {sym}\n{down}", 8000)
        else:
            self.say(f"This is your card: {name} {sym}\n{up}", 8000)
        self.happy = 0

    def castle_done(self):
        if self.activity and not self.reminder_active:
            self.say(random.choice(["Ta-da! \U0001F3F0", "My masterpiece~", "Don't touch it! Hehe"]), 3000)
            self.happy = 0

    def castle_broken(self):
        self.pout_until = time.time() + 4
        self.floor_sit = False                  # she stands up in a huff
        self.happy = 0
        self.say(random.choice(["Rude!", "Rude!! \U0001F4A2", "Hey! Rude~", "...Rude.",
                                "I worked hard on that! Rude!"]), 3000)
        if self.activity:
            self.activity["until"] = time.time() + 4.5

    def bite(self, n):
        a = self.activity
        if n >= 3:
            self.say("All gone! Yummy~ \u2665", 2500)
            self.hearts.append([random.randint(80, 140), 90, 0, "\u2665"])
            QTimer.singleShot(700, self.end_activity)
            if a:
                a["until"] = time.time() + 5
        else:
            self.say(random.choice(["Nom!", "Good, right?", "Hehe, crumbs~", "Share with me!"]), 1500)

    def end_activity(self, quiet=False):
        if self.card:
            self.card.close()
            self.card = None
        if self.snack:
            self.snack.close()
            self.snack = None
        if self.castle and not self.castle.broken:
            self.castle.close()
            self.castle = None
        if self.crystal:
            self.crystal.close()
            self.crystal = None
        if self.bouquet and not self.bouquet.taken:
            self.bouquet.close()
            self.bouquet = None
        if self.activity and self.activity.get("spot") == "window":
            self.sitting = False
            self.set_mode("wander", random.uniform(10, 20))
        self.activity = None
        self.floor_sit = False

    # ---------- nap beds ----------
    BED_NAMES = {"futon": "Futon", "petbed": "Pet bed", "dock": "Charging dock"}

    def beds_available(self):
        return [b for b in self.BED_NAMES if ("sleep_" + b) in self.frames]

    def update_bed(self):
        if not self.sleep_hours and self.bed is None:
            self.test_bed = None
        want = (self.sleep_hours and not self.dragging and not self.falling
                and not self.reminder_active and not self.singing)
        if want and self.bed is None:
            choice = self.test_bed or self.bed_choice
            avail = self.beds_available()
            if choice == "random":
                choice = random.choice(avail) if avail else "none"
            if choice != "none" and choice in avail:
                self.bed = choice
                self.poof = 14
                if self.sitting:
                    self.sitting = False
                    if self.cur_window is not None:
                        self.py = float(self.cur_window.top() - 221)
                        self.move(int(self.px), int(self.py))
        elif not want and self.bed is not None:
            self.bed = None
            self.poof = 14
        if self.poof > 0:
            self.poof -= 1

    def set_bed_choice(self, choice):
        self.bed_choice = choice
        label = {"random": "a surprise bed", "none": "no bed"}.get(choice, self.BED_NAMES.get(choice))
        self.say(f"Nap time = {label}!", 2000)

    def test_nap(self, bed):
        self.test_bed = bed
        self.bed = None
        self.nap_now()

    def draw_poof(self, p):
        k = (14 - self.poof) / 14.0
        p.setPen(Qt.NoPen)
        for i in range(7):
            a = math.radians(i * 360 / 7 + 20)
            r = 18 + 45 * k
            x = 110 + math.cos(a) * r * 1.4
            y = 205 + math.sin(a) * r * 0.5
            p.setBrush(QBrush(QColor(255, 255, 255, int(230 * (1 - k)))))
            p.drawEllipse(QPointF(x, y), 16 * (1 - 0.4 * k), 13 * (1 - 0.4 * k))

    def draw_pout(self, p, b):
        """A little red anger mark by her head, plus puffed-cheek blush."""
        cx, cy = 152, 62 + b
        p.setPen(QPen(QColor("#e0393e"), 3, Qt.SolidLine, Qt.RoundCap))
        starts = {(-1, -1): 270, (1, -1): 180, (-1, 1): 0, (1, 1): 90}
        for (dx, dy), start in starts.items():
            p.drawArc(QRectF(cx + dx * 6 - 6, cy + dy * 6 - 6, 12, 12), start * 16, 90 * 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(255, 110, 150, 150)))
        p.drawEllipse(QPointF(80, 112 + b), 9, 5)
        p.drawEllipse(QPointF(140, 112 + b), 9, 5)

    def draw_low_battery(self, p):
        """A little empty, blinking-red battery by her head while she's hungry for a charge."""
        x, y = 152, 54
        p.setPen(QPen(QColor("#1b1b1b"), 2))
        p.setBrush(QBrush(QColor("white")))
        p.drawRoundedRect(QRectF(x, y, 26, 13), 3, 3)
        p.drawRect(QRectF(x + 26, y + 3.5, 3, 6))
        if (self.t // 12) % 2 == 0:
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor("#e8383f")))
            p.drawRect(QRectF(x + 2.5, y + 2.5, 5, 8))

    def draw_battery(self, p):
        level = ((self.t // 15) % 5) / 4.0
        x, y = 42, 80
        p.setPen(QPen(QColor("#1b1b1b"), 2))
        p.setBrush(QBrush(QColor("white")))
        p.drawRoundedRect(QRectF(x, y, 30, 15), 3, 3)
        p.drawRect(QRectF(x + 30, y + 4, 3, 7))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#5fd38a")))
        p.drawRect(QRectF(x + 2.5, y + 2.5, 25 * level, 10))
        p.setPen(QPen(QColor("#f5b700")))
        p.setFont(QFont("Helvetica", 11, QFont.Bold))
        p.drawText(QPointF(x + 9, y + 12.5), "\u26a1")

    def nap_now(self):
        self.say("*yawn*... just a little nap~", 2000)
        self.nap_until = time.time() + 32
        QTimer.singleShot(2000, self.start_nap)

    def start_nap(self):
        if time.time() < self.nap_until:
            self.msg = None
            self.sleep_hours = True

    def wake_up(self):
        self.nap_until = 0
        self.test_bed = None
        self.sleep_hours = in_sleep_hours()
        self.say("I'm up, I'm up!", 1800)
        self.jump = 15

    def sit_now(self):
        if "sit" not in self.frames:
            self.say("I don't have my sitting pose yet!", 2500)
            return
        w = self.get_front_window() if HAS_WINLIST else None
        if w is None or not self.can_perch(w):
            self.say("No window with room on top for me~", 2500)
            return
        self.cur_window = w
        self.set_mode("perch", 45)
        self.want_sit = True
        self.happy = 0
        self.say("Ooh, a seat!", 1500)

    def peek_now(self):
        w = self.get_front_window() if HAS_WINLIST else None
        if w is None:
            self.say("I can't see any windows to hide behind~", 2500)
            return
        sides = [x for x in ("top", "right", "left") if self.can_peek(w, x)]
        if not sides:
            self.say("That window's too big to hide behind~ Try one that isn't full screen!", 3500)
            return
        self.cur_window = w
        self.peek_side = random.choice(sides)
        if self.peek_side == "top":
            lo, hi = w.left() - 20, w.right() - 200
            if hi < lo:
                lo = hi = w.center().x() - 110
            self.peek_x = random.randint(int(lo), int(hi))
        self.set_mode("peek", 15)

    def open_birthdays(self):
        if self.birthday_win is None:
            self.birthday_win = BirthdayManager(self)
        self.birthday_win.refresh()
        self.birthday_win.show()
        self.birthday_win.raise_()
        self.birthday_win.activateWindow()

    def open_reminders(self):
        if self.reminder_win is None:
            self.reminder_win = ReminderManager(self)
        self.reminder_win.refresh()
        self.reminder_win.show()
        self.reminder_win.raise_()
        self.reminder_win.activateWindow()

    def add_toggle(self, menu, label, value, setter):
        action = menu.addAction(label)
        action.setCheckable(True)
        action.setChecked(value)
        action.toggled.connect(setter)

    def set_wander(self, value):
        self.wander = value

    def set_follow(self, value):
        self.follow_enabled = value
        if not value and self.mode == "follow":
            self.set_mode("wander", random.uniform(10, 20))

    def set_windows(self, value):
        self.windows_enabled = value
        if not value and self.mode in ("perch", "peek"):
            self.set_mode("wander", random.uniform(10, 20))

    def set_sing(self, value):
        self.sing_enabled = value

    def set_dance(self, value):
        self.dance_enabled = value

    def set_react(self, value):
        self.react_enabled = value

    def set_steam(self, value):
        self.steam_enabled = value

    def set_game_mode(self, value):
        self.game_mode = value
        if not value:
            self.cheer_next = 0

    def set_welcome(self, value):
        self.welcome_enabled = value

    def set_eye(self, value):
        self.eye_enabled = value
        self.eye_last = time.time()

    # ---------- behavior ----------
    def say(self, text, ms=2200):
        if self.intro_step >= 0 and not self.intro_talking:
            return                          # during the hello tour only the tour talks
        self.msg = text
        self.msg_ticks = int(ms / 40)

    def tour_say(self, text, ms):
        self.intro_talking = True
        self.say(text, ms)
        self.intro_talking = False

    def poke(self):
        if self.mode == "peek":
            self.set_mode("wander", random.uniform(10, 25))
            self.say("Peekaboo!", 1800)
            self.happy = 30
            self.hearts.append([random.randint(80, 140), 90, 0, "\u2665"])
            return
        self.happy = 40
        if self.sleepy:
            self.say(random.choice(SLEEPY_POKE_LINES))
        else:
            self.say(random.choice(POKE_LINES))
        for _ in range(3):
            self.hearts.append([random.randint(80, 140), 90, 0, "\u2665"])

    def come_here(self):
        self.set_mode("follow", 12)
        self.say("Coming~", 1500)

    def remind(self, text):
        if self.med_end:
            self.med_pending.append(text)       # it'll wait until you're done breathing
            return
        if "stretch" in text.lower():
            self.stretch_until = time.time() + 8
        if "water" in text.lower():
            text = f"{text} ({self.water_today()}/{self.water['goal']} today)"
        self.last_reminder = text
        self.reminder_active = True
        self.happy = 0
        self.say(text, 15000)
        QApplication.beep()

    def next_outfit(self):
        i = ACC_MODES.index(self.acc_mode)
        self.acc_mode = ACC_MODES[(i + 1) % len(ACC_MODES)]
        if not self.reminder_active:
            self.say(ACC_NAMES[self.acc_mode], 1800)
        self.happy = 15

    # ---------- customizing ----------
    def open_customize(self, page=None):
        self.dragging = False
        self.ptt_timer.stop() if hasattr(self, "ptt_timer") else None
        if self.custom_win is None:
            self.custom_win = CustomizeDialog(self)
        self.custom_win.refresh()
        if page is not None:
            self.custom_win.show_page(page)
        self.custom_win.show()
        self.custom_win.raise_()
        self.custom_win.activateWindow()

    def set_hair(self, hx):
        self.hair_color = hx
        self.tint_cache = {}
        self.style_cache = {}
        self.save_custom()
        has_layers = self.layered_hair() or any(v for lst in self.hair_layers.values() for v in lst)
        if hx and not has_layers:
            self.say("I need my hair layers rendered first! (ask Claude~)", 3500)
        elif not self.reminder_active:
            name = next((n for n, h in HAIR_COLORS if h == hx), None)
            self.say(f"New hair! {name or ''} \u2728" if hx else "Back to my usual hair~", 2000)
        self.happy = 15

    def split_bottoms(self):
        """True once her frames are rendered without a skirt (skirt/shorts come as layers)."""
        if not hasattr(self, "_split_bottoms"):
            folder = getattr(self, "frames_folder", None)
            self._split_bottoms = bool(folder) and os.path.isdir(os.path.join(folder, "bottom_skirt"))
        return self._split_bottoms

    def bottom_layers(self):
        """{state: [layer]} for the skirt or shorts she's wearing, loaded on first use."""
        if self.bottom in self.bottom_cache:
            return self.bottom_cache[self.bottom]
        layers = {}
        folder = getattr(self, "frames_folder", None)
        if folder:
            bdir = os.path.join(folder, "bottom_" + self.bottom)
            if os.path.isdir(bdir):
                for name in sorted(os.listdir(folder)):
                    if name.endswith(".png") and "_" in name:
                        st = name.rsplit("_", 1)[0]
                        bp = os.path.join(bdir, name)
                        layers.setdefault(st, []).append(QPixmap(bp) if os.path.exists(bp) else None)
        self.bottom_cache = {self.bottom: layers}          # keep only the one she's wearing
        return layers

    def bottom_for(self, state, k):
        if not self.split_bottoms():
            return None
        if state.startswith("peek"):
            return None         # peeking: only her head shows, the window hides her skirt/shorts
        return self.layer_pixmap(os.path.join(self.frames_folder, "bottom_" + self.bottom,
                                              "%s_%02d.png" % (state, k)))

    def set_bottom(self, key):
        if key != "skirt" and not self.split_bottoms():
            self.say("I need my shorts rendered first! (ask Claude~)", 3500)
            return
        self.bottom = key
        self.save_custom()
        if not self.reminder_active:
            self.say("Shorts day! \u2728" if key == "shorts" else "Skirt time~", 2000)
        self.happy = 15

    def layered_hair(self):
        """True once her frames are rendered without hair (each hair style is its own layer)."""
        if not hasattr(self, "_layered_hair"):
            folder = getattr(self, "frames_folder", None)
            self._layered_hair = bool(folder) and os.path.isdir(os.path.join(folder, "hairstyle_twintails"))
        return self._layered_hair

    def style_layer(self, folder, state, k):
        """Her hair style's layer for this frame: the gray one (for tinting) if she has a hair
        color picked, otherwise the original colors. Loaded the first time it's needed."""
        if not folder or not self.layered_hair():
            return None
        sub = os.path.join("hairstyle_" + self.hairstyle, "gray") if self.hair_color else \
            "hairstyle_" + self.hairstyle
        return self.layer_pixmap(os.path.join(folder, sub, "%s_%02d.png" % (state, k)))

    def layer_pixmap(self, path):
        """One layer picture, loaded the first time it's needed (None if there isn't one)."""
        cache = getattr(self, "style_cache", None)
        if cache is None:
            cache = self.style_cache = {}
        if path not in cache:
            if len(cache) > 1500:
                cache.clear()
            pm = QPixmap(path) if os.path.exists(path) else None
            cache[path] = pm if pm is not None and not pm.isNull() else None
        return cache[path]

    def set_hairstyle(self, key):
        if key != "twintails" and not self.layered_hair():
            self.say("I need my new hair styles rendered first! (ask Claude~)", 3500)
            return
        self.hairstyle = key
        self.style_cache = {}
        self.outfit_cache = {}
        self.tint_cache = {}
        self.save_custom()
        if not self.reminder_active:
            name = dict(HAIR_STYLES).get(key, "")
            self.say(f"New look! {name} \u2728", 2000)
        self.happy = 15

    def glow_for(self, target, pm, hl, bl):
        """A soft white outline around her whole shape (so she shows up on dark windows).
        Made at the size she's drawn and remembered per frame."""
        w, h = max(1, int(round(target.width()))), max(1, int(round(target.height())))
        key = (pm.cacheKey(), hl.cacheKey() if hl is not None else 0,
               bl.cacheKey() if bl is not None else 0, w, h)
        cache = getattr(self, "glow_cache", None)
        if cache is None:
            cache = self.glow_cache = {}
        g = cache.get(key)
        if g is not None:
            return g
        from PySide6.QtGui import QImage
        # 1. her silhouette (frame + bottoms + hair) at the size she's drawn
        sil = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        sil.fill(Qt.transparent)
        q = QPainter(sil)
        q.setRenderHint(QPainter.SmoothPixmapTransform)
        full = QRectF(0, 0, w, h)
        q.drawPixmap(full, pm, QRectF(pm.rect()))
        for lay in (bl, hl):
            if lay is not None and not lay.isNull():
                hh = h * lay.height() / pm.height()
                q.drawPixmap(QRectF(0, h - hh, w, hh), lay, QRectF(lay.rect()))
        q.end()
        # 2. spread it out a few pixels in every direction, then paint that white
        out = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        out.fill(Qt.transparent)
        q = QPainter(out)
        for rad, alpha in ((2.6, 0.45), (1.4, 1.0)):
            q.setOpacity(alpha)
            for i in range(16):
                a = 2 * math.pi * i / 16
                q.drawImage(QPointF(rad * math.cos(a), rad * math.sin(a)), sil)
        q.setOpacity(1.0)
        q.setCompositionMode(QPainter.CompositionMode_SourceIn)
        q.fillRect(out.rect(), QColor(255, 255, 255, 215))
        q.end()
        g = QPixmap.fromImage(out)
        if len(cache) > 300:
            cache.clear()
        cache[key] = g
        return g

    def draw_layers(self, p, target, pm, hl, bl):
        """Her frame, her skirt or shorts, then her hair on top (tinted if a color is picked).
        (Older frames had the hair built in, so then only the tint goes on, under the bottoms.)"""
        if getattr(self, "outline", "glow") == "glow":
            try:
                hl2 = hl
                if hl is not None and self.hair_color and not hl.isNull():
                    hl2 = self.tinted(hl)
                p.drawPixmap(target, self.glow_for(target, pm, hl2 if self.layered_hair() else None, bl),
                             QRectF(0, 0, round(target.width()), round(target.height())))
            except Exception as ex:
                print("glow failed:", ex, file=sys.stderr, flush=True)
                self.outline = "off"
        p.drawPixmap(target, pm, QRectF(pm.rect()))
        if bl is not None and not bl.isNull() and bl.height() != pm.height():
            # skirt/shorts layers are made with the normal camera; outfit frames have extra room
            # above her head, so line it up by the floor (same scale, same bottom edge)
            hh = target.height() * bl.height() / pm.height()
            btarget = QRectF(target.x(), target.bottom() - hh, target.width(), hh)
        else:
            btarget = target
        if self.layered_hair():
            if bl is not None and not bl.isNull():
                p.drawPixmap(btarget, bl, QRectF(bl.rect()))
            if hl is not None and not hl.isNull():
                tp = self.tinted(hl) if self.hair_color else hl
                p.drawPixmap(target, tp, QRectF(tp.rect()))
            return
        if self.hair_color and hl is not None and not hl.isNull():
            tp = self.tinted(hl)
            p.drawPixmap(target, tp, QRectF(tp.rect()))
        if bl is not None and not bl.isNull():
            p.drawPixmap(btarget, bl, QRectF(bl.rect()))

    def tinted(self, hair_pm):
        """Her gray hair layer, colored in the chosen color (shading and outlines kept)."""
        key = (hair_pm.cacheKey(), self.hair_color)
        tp = self.tint_cache.get(key)
        if tp is None:
            tp = QPixmap(hair_pm.size())
            tp.fill(Qt.transparent)
            q = QPainter(tp)
            q.drawPixmap(0, 0, hair_pm)
            q.setCompositionMode(QPainter.CompositionMode_Multiply)
            q.fillRect(tp.rect(), QColor(self.hair_color))
            q.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            q.drawPixmap(0, 0, hair_pm)
            q.end()
            if len(self.tint_cache) > 600:
                self.tint_cache = {}
            self.tint_cache[key] = tp
        return tp

    def preview_pixmap(self, k=0, w=220, h=260):
        """What she looks like right now, for the customize window. k = animation step (she idles and blinks)."""
        out = QPixmap(w, h)
        out.fill(Qt.transparent)
        acc = self.current_accessory()
        blink = (k % 45) in (0, 1)             # a blink every few seconds

        def pick(frames_by_state):
            for st in (("blink", "idle") if blink else ("idle",)):
                fr = frames_by_state.get(st)
                if fr:
                    return st, k % len(fr) if st == "idle" else 0, fr
            return None, 0, None

        pm, hl, state, idx = None, None, "idle", 0
        used_3d = False
        if acc and self.outfit_style == "3d":
            d = self.outfit_frames(acc)
            st, i, fr = pick(d)
            if fr:
                state, idx, pm = st, i, fr[i]
                used_3d = True
                if self.layered_hair():
                    hl = self.style_layer(getattr(self, "outfit_folder", None), st, i)
                else:
                    hs = getattr(self, "outfit_hair", {}).get(st) or [None]
                    hl = hs[i] if i < len(hs) else hs[0]
        if pm is None:
            st, i, fr = pick(self.frames)
            if fr:
                state, idx, pm = st, i, fr[i]
                if self.layered_hair():
                    hl = self.style_layer(self.frames_folder, st, i)
                else:
                    hs = self.hair_layers.get(st) or [None]
                    hl = hs[i] if i < len(hs) else hs[0]
        if pm is None:
            return out
        q = QPainter(out)
        q.setRenderHint(QPainter.SmoothPixmapTransform)
        q.setRenderHint(QPainter.Antialiasing)
        q.scale(w / 220, h / 260)
        extra = (pm.height() - 480) * 0.431
        target = QRectF(15, 38 + 20 - extra, 190, 207 + extra)
        self.draw_layers(q, target, pm, hl, self.bottom_for(state, idx))
        if acc and not used_3d:
            self.draw_pinned_accessory(q, pm, target, acc)      # drawn outfit, pinned to her head
        q.end()
        return out

    def save_custom(self):
        try:
            with open(CUSTOM_FILE, "w") as f:
                json.dump({"hair": self.hair_color, "outfit": self.acc_mode,
                           "style": self.outfit_style, "hairstyle": self.hairstyle,
                           "bottom": self.bottom, "bubble": self.bubble_mode,
                           "bubble_shape": self.bubble_shape, "bubble_pos": self.bubble_pos, "nickname": self.nickname,
                           "text_size": self.text_size, "outline": self.outline,
                           "glow_told": self.glow_told, "place": self.place, "units": self.units,
                           "dnd_days": self.dnd_days, "dnd_games": self.dnd_games,
                           "dnd_opts": self.dnd_opts, "dnd_init": self.dnd_init,
                           "sleep_hours": self.sleep_hours_set,
                           "birthdays": self.birthdays, "my_birthday": self.my_birthday,
                           "med_days": self.med_days[-400:], "med_total": self.med_total,
                           "med_guide": self.med_guide, "med_time": self.med_time,
                           "med_asked_day": self.med_asked_day, "med_sound": self.med_sound,
                           "med_volume": self.med_volume, "med_chime": self.med_chime,
                           "intro_done": self.intro_done, "rps": self.rps,
                           "trivia_best": self.trivia_best, "trivia_mine": self.trivia_mine}, f)
        except Exception:
            pass

    def apply_personal(self, d):
        """Name, city, units, game nights and bedtime from a settings dict."""
        global SLEEP_HOURS
        if isinstance(d.get("nickname"), str):
            self.nickname = d["nickname"][:24]
        pl = d.get("place")
        if isinstance(pl, dict) and "lat" in pl and "lon" in pl:
            self.place = {"name": str(pl.get("name", "")), "lat": float(pl["lat"]), "lon": float(pl["lon"])}
        elif "place" in d and pl is None:
            self.place = None
        if d.get("units") in ("F", "C"):
            self.units = d["units"]
        if isinstance(d.get("dnd_days"), list):
            self.dnd_days = [x for x in d["dnd_days"] if x in DAY_ORDER]
        if isinstance(d.get("dnd_games"), list):
            self.dnd_games = [g for g in (clean_dnd_game(x) for x in d["dnd_games"]) if g]
        elif self.dnd_days and not self.dnd_games:
            # game nights from before the D&D tab: one game, 7pm on those days
            self.dnd_games = [clean_dnd_game({"title": "Game night", "days": self.dnd_days,
                                              "start": "19:00", "hours": 4})]
        if isinstance(d.get("trivia_mine"), list):
            self.trivia_mine = [t for t in (clean_trivia(x) for x in d["trivia_mine"]) if t][:300]
        if isinstance(d.get("trivia_best"), dict):
            self.trivia_best = {k: int(v) for k, v in d["trivia_best"].items()
                                if k in TRIVIA_NAMES and isinstance(v, (int, float))}
        if isinstance(d.get("rps"), dict):
            for k in ("you", "digi", "tie"):
                if isinstance(d["rps"].get(k), int):
                    self.rps[k] = max(0, d["rps"][k])
        if isinstance(d.get("dnd_opts"), dict):
            for k in ("use_name", "dress", "notes_pin"):
                if k in d["dnd_opts"]:
                    self.dnd_opts[k] = bool(d["dnd_opts"][k])
            if isinstance(d["dnd_opts"].get("notes_font"), (int, float)):
                self.dnd_opts["notes_font"] = max(10, min(32, int(d["dnd_opts"]["notes_font"])))
            geo = d["dnd_opts"].get("notes_geo")
            if isinstance(geo, list) and len(geo) == 4 and all(isinstance(v, (int, float)) for v in geo):
                self.dnd_opts["notes_geo"] = [int(v) for v in geo]
        ini = d.get("dnd_init")
        if isinstance(ini, dict) and isinstance(ini.get("order"), list):
            order = []
            for e in ini["order"]:
                if not (isinstance(e, (list, tuple)) and len(e) in (2, 4)
                        and all(isinstance(v, (int, float)) for v in e[1:])):
                    continue
                if len(e) == 2:                    # saved before modifiers: the roll was the total
                    order.append([str(e[0])[:24], int(e[1]), 0, int(e[1])])
                else:
                    order.append([str(e[0])[:24], int(e[1]), int(e[2]), int(e[3])])
            self.dnd_init = {"order": order[:30], "manual": bool(ini.get("manual", False)),
                             "turn": int(ini.get("turn", 0)) if order else 0,
                             "round": max(1, int(ini.get("round", 1)))}
        self.dnd_sync_days()
        if isinstance(d.get("birthdays"), list):
            self.birthdays = [b for b in (clean_birthday(x) for x in d["birthdays"]
                                          if isinstance(x, dict) and "name" in x) if b]
        if isinstance(d.get("med_days"), list):
            self.med_days = [str(x) for x in d["med_days"] if isinstance(x, str)][-400:]
        if isinstance(d.get("med_total"), (int, float)):
            self.med_total = int(d["med_total"])
        if "med_guide" in d:
            self.med_guide = bool(d["med_guide"])
        if d.get("med_time") is None or re.fullmatch(r"\d\d:\d\d", str(d.get("med_time"))):
            self.med_time = d.get("med_time")
        if d.get("med_sound") in [k for k, _ in MED_SOUNDS]:
            self.med_sound = d["med_sound"]
        if d.get("med_chime") in [k for k, _ in MED_CHIMES]:
            self.med_chime = d["med_chime"]
        if isinstance(d.get("med_volume"), (int, float)):
            self.med_volume = max(0.0, min(1.0, float(d["med_volume"])))
        if isinstance(d.get("med_asked_day"), str):
            self.med_asked_day = d["med_asked_day"]
        if "my_birthday" in d:
            mb = d["my_birthday"]
            self.my_birthday = clean_birthday(mb) if isinstance(mb, dict) else None
        sh = d.get("sleep_hours")
        if sh is None and "sleep_hours" in d:
            self.sleep_hours_set = None
        elif isinstance(sh, (list, tuple)) and len(sh) == 2:
            self.sleep_hours_set = [str(sh[0]), str(sh[1])]
        SLEEP_HOURS = tuple(self.sleep_hours_set) if self.sleep_hours_set else None

    def load_custom(self):
        try:
            with open(CUSTOM_FILE) as f:
                d = json.load(f)
            self.hair_color = d.get("hair")
            if d.get("outfit") in ACC_MODES:
                self.acc_mode = d["outfit"]
            if d.get("style") in ("3d", "drawn"):
                self.outfit_style = d["style"]
            if d.get("hairstyle") in [k for k, _ in HAIR_STYLES]:
                self.hairstyle = d["hairstyle"]
            if d.get("bottom") in [k for k, _ in BOTTOMS]:
                self.bottom = d["bottom"]
            self.apply_personal(d)
            if d.get("bubble") in ("light", "dark"):
                self.bubble_mode = d["bubble"]
            if d.get("bubble_shape") in ("speech", "thought"):
                self.bubble_shape = d["bubble_shape"]
            if d.get("bubble_pos") in ("above", "side"):
                self.bubble_pos = d["bubble_pos"]
            if d.get("outline") in ("glow", "off"):
                self.outline = d["outline"]
            self.glow_told = bool(d.get("glow_told", False))
            # someone who already had Digi before the tour existed has met her already
            self.intro_done = bool(d.get("intro_done", True))
            if d.get("text_size") in ("small", "medium", "large"):
                self.text_size = d["text_size"]
        except Exception:
            pass

    def set_outfit(self, mode):
        self.acc_mode = mode
        self.save_custom()
        if not self.reminder_active:
            self.say(ACC_NAMES[mode], 1800)
        self.happy = 15

    def set_outfit_style(self, style):
        self.outfit_style = style
        self.save_custom()
        self.say("3D outfits!" if style == "3d" else "Drawn outfits!", 1800)

    def outfit_frames(self, acc):
        """Frames of her wearing a 3D outfit, loaded the first time it's worn."""
        # the bigger hair styles have their own Santa/witch frames (hat a bit lower and bigger),
        # and some hats (the sun hat) have frames made just for one hair style
        names = ["outfit_" + acc]
        if self.hairstyle in ("shaggy", "swept"):
            names.insert(0, "outfit_" + acc + "-big")
        names.insert(0, "outfit_" + acc + "-" + self.hairstyle)
        key = (acc, names[0])
        if key in self.outfit_cache:
            return self.outfit_cache[key]
        frames = {}
        hair = {}
        folder = None
        here = os.path.dirname(os.path.abspath(__file__))
        cands = [os.path.join(b, n) for b in (os.path.join(here, "pet_frames"),
                                              os.path.expanduser("~/Downloads/pet_frames"))
                 for n in names]
        for folder in cands:
            if os.path.isdir(folder):
                paths, hpaths = {}, {}
                for name in sorted(os.listdir(folder)):
                    if name.endswith(".png") and "_" in name:
                        st = name.rsplit("_", 1)[0]
                        paths.setdefault(st, []).append(os.path.join(folder, name))
                        hpaths.setdefault(st, []).append(os.path.join(folder, "hair", name))
                frames = {st: LazyPix(v) for st, v in paths.items()}
                hair = {st: LazyPix(v, optional=True) for st, v in hpaths.items()}
                if frames:
                    break
        self.outfit_cache = {key: frames}       # keep only the one she's wearing
        self.outfit_hair = hair
        self.outfit_folder = folder if frames else None
        return frames

    def current_accessory(self):
        if getattr(self, "dnd_mode", False):
            return "book"                                            # her solo campaign
        s = self.dnd_now() if self.dnd_games else None
        if s and self.dnd_opts.get("dress", True):
            return "book" if s[0]["role"] == "dm" else "sword"      # game time!
        if self.acc_mode == "none":
            return None
        if self.acc_mode != "auto":
            return self.acc_mode
        d = date.today()
        # party days first: New Year's, Digi's birthday, your birthday
        if (d.month, d.day) in ((12, 31), (1, 1)) or self.is_digi_birthday(d) or self.is_my_birthday(d):
            return "party"
        if d.month == 2 and 7 <= d.day <= 14:
            return "heart"
        if -6 <= (d - easter(d.year)).days <= 1:
            return "bunny"                      # the week before Easter through Easter Monday
        if d.month == 10:
            return "witch"
        if d.month == 12 or (d.month == 1 and d.day <= 5):
            return "santa"
        if d.month in (3, 4, 5):
            return "flower"
        if d.month in (11, 1, 2):
            return "scarf"
        if d.month in (6, 7, 8):
            return "sunhat"
        if d.month == 9:
            return "beret"
        return None

    # ----- focus timer + pomodoro -----
    def start_focus(self, minutes):
        self.pomo = False
        self.break_end = None
        self.focus_end = time.time() + minutes * 60
        self.say(f"Focus time! {minutes_label(minutes)}. You've got this!", 3500)
        self.happy = 20

    def start_pomodoro(self):
        self.pomo = True
        self.break_end = None
        self.focus_end = time.time() + POMODORO_FOCUS * 60
        self.say(f"Pomodoro! {POMODORO_FOCUS} minutes of focus~", 3500)
        self.happy = 20

    def stop_focus(self):
        self.focus_end = None
        self.break_end = None
        self.pomo = False
        self.say("Timer stopped. Nice try!", 2000)

    # ----- meditation -----
    def start_meditation(self, minutes):
        if self.focus_end or self.break_end:
            self.focus_end = self.break_end = None
            self.pomo = False
        if self.activity:
            self.end_activity(quiet=True)
        self.close_choices()
        self.med_asking = False
        self.med_awaiting_more = False
        self.med_minutes_set = minutes
        self.med_start = time.time()
        self.med_end = self.med_start + minutes * 60
        self.med_phase = -1
        self.happy = 0
        self.say(random.choice(MED_START_LINES), 3500)
        self.preview_until = 0
        self.med_round_start = self.med_start
        self.med_mid_done = False
        QTimer.singleShot(1200, lambda: self.play_chime("start") if self.med_end else None)

    def show_choices(self, options, on_pick, active=None, big=False, timeout=None):
        if self.choice_bar is not None:
            try:
                self.choice_bar.hide()
                self.choice_bar.deleteLater()
            except Exception:
                pass
        def picked(key):
            self.choice_bar = None
            on_pick(key)
        self.choice_bar = ChoiceBar(self, options, picked, active, big)
        self.choice_big = big
        self.choice_since = time.time()
        self.choice_timeout = timeout or (45 if big else None)
        self.choice_pick = picked

    def close_choices(self):
        if self.choice_bar is not None:
            try:
                self.choice_bar.hide()
                self.choice_bar.deleteLater()
            except Exception:
                pass
            self.choice_bar = None

    def check_med_invite(self):
        """Her daily meditation invite (and "Later" asking again)."""
        if self.intro_step >= 0:
            return
        now = datetime.now()
        if self.med_asking:
            if time.time() - self.med_asked_since > MED_ANSWER_WAIT:
                self.answer_invite("later", quiet=True)
            return
        if self.med_end or self.bed or self.sleep_hours or self.reminder_active or self.dragging:
            return
        due = False
        if self.med_ask_at and time.time() >= self.med_ask_at:
            due = True
        elif self.med_time and self.med_asked_day != now.strftime("%Y-%m-%d") and not self.med_ask_at:
            due = now.strftime("%H:%M") >= self.med_time
        if not due:
            return
        if self.focus_end or self.streaming:
            self.med_ask_at = time.time() + MED_LATER * 60     # busy (focus timer / movie): try later
            return
        self.invite_meditation()

    def invite_meditation(self):
        if self.activity:
            self.end_activity(quiet=True)
        self.med_ask_at = None
        self.med_asking = True
        self.med_asked_since = time.time()
        self.say("Ready for a little meditation? \U0001F9D8", MED_ANSWER_WAIT * 1000)
        self.show_choices([("Yes", "yes"), ("Later", "later"), ("No", "no")], self.answer_invite)

    def answer_invite(self, key, quiet=False):
        self.med_asking = False
        self.close_choices()
        today = date.today().isoformat()
        if key == "yes":
            self.med_asked_day = today
            self.save_custom()
            self.say("Yay! How long should we go?", 60000)
            self.show_choices([(f"{m} min", m) for m in MED_CHOICES], self.pick_med_length)
        elif key == "later":
            self.med_ask_at = time.time() + MED_LATER * 60
            if not quiet:
                self.say(f"Okay! I'll ask again in {MED_LATER} minutes~", 3000)
            else:
                self.msg = None
        else:
            self.med_asked_day = today
            self.med_ask_at = None
            self.save_custom()
            self.say("Okay! Maybe tomorrow~ \u2665", 2500)

    def pick_med_length(self, minutes):
        self.start_meditation(int(minutes))

    def ask_keep_going(self):
        """Time's up: chime, then ask if you'd like to keep going (same length again)."""
        self.med_awaiting_more = True
        self.med_asked_since = time.time()
        self.play_chime("end")
        self.say("Time's up~ Want to keep going?", 120000)
        m = self.med_minutes_set
        self.show_choices([(f"Yes (+{m} min)", "yes"), ("No", "no")], self.answer_keep_going)

    def answer_keep_going(self, key):
        self.med_awaiting_more = False
        self.close_choices()
        if key == "yes" and self.med_end:
            # keep going: another round of the same length, so your time doubles
            self.med_end = time.time() + self.med_minutes_set * 60
            self.med_round_start = time.time()
            self.med_mid_done = False
            self.play_chime("start")
            self.med_phase = -1
            self.say("Okay~ let's keep breathing \U0001F33F", 3000)
        else:
            self.stop_meditation(chimed=True)

    def set_med_time(self, hhmm):
        self.med_time = hhmm
        self.med_ask_at = None
        if hhmm and datetime.now().strftime("%H:%M") >= hhmm:
            self.med_asked_day = date.today().isoformat()     # set after today's time: start tomorrow
        self.save_custom()

    def set_med_guide(self, value):
        self.med_guide = value
        self.save_custom()

    def med_streak(self):
        days = set(self.med_days)
        d = date.today()
        if d.isoformat() not in days:
            d -= timedelta(days=1)            # today doesn't count yet: the streak still holds
        n = 0
        while d.isoformat() in days:
            n += 1
            d -= timedelta(days=1)
        return n

    def say_med_stats(self):
        if not self.med_days:
            self.say("We haven't meditated together yet~ Want to try a 1 minute one?", 4000)
            return
        n = self.med_streak()
        days = len(set(self.med_days))
        streak = (f"{n} day{'s' if n != 1 else ''} in a row! " if n > 1 else "")
        self.say(f"{streak}{days} day{'s' if days != 1 else ''} of meditating together, "
                 f"{self.med_total} minutes in all \U0001F33F", 6000)

    def stop_meditation(self, early=False, chimed=False):
        if not self.med_end:
            return
        self.close_choices()
        self.med_awaiting_more = False
        done = (min(time.time(), self.med_end) - (self.med_start or time.time())) / 60
        self.med_end = None
        self.med_phase = -1
        if done >= 1 or not early:
            self.med_total += max(1, int(round(done)))
            today = date.today().isoformat()
            if today not in self.med_days:
                self.med_days.append(today)
            self.save_custom()
        if early:
            self.say("That's okay~ Every little breath counts \u2665", 3000)
        else:
            if not chimed:
                self.play_chime("end")
            n = self.med_streak()
            line = random.choice(MED_END_LINES)
            if n > 1:
                line += f"  ({n} days in a row!)"
            self.say(line, 6000)
            for _ in range(4):
                self.hearts.append([random.randint(70, 150), 90, 0, "\u2665"])
        if self.med_pending:
            waiting, self.med_pending = self.med_pending, []
            QTimer.singleShot(6500, lambda: self.remind("  \u2022  ".join(waiting)))

    def check_meditation(self):
        if not self.med_end:
            return
        now = time.time()
        if self.med_awaiting_more:
            if now - self.med_asked_since > 120:
                self.answer_keep_going("no")
            return
        if now >= self.med_end:
            self.ask_keep_going()
            return
        rs = getattr(self, "med_round_start", self.med_start) or now
        if not getattr(self, "med_mid_done", True) and now >= rs + (self.med_end - rs) / 2:
            self.med_mid_done = True
            self.play_chime("middle")             # halfway there
        if self.med_guide:
            # cycle: in / hold / out, shown in her bubble
            total = sum(sec for _, sec in BREATH)
            t = (now - self.med_start) % total
            i = 0
            while t >= BREATH[i][1]:
                t -= BREATH[i][1]
                i += 1
            if i != self.med_phase and now - self.med_start > 3.5:
                self.med_phase = i
                self.say(BREATH[i][0], int(BREATH[i][1] * 1000))

    def breath_amount(self):
        """0 (breathed out) .. 1 (full breath), following the in / hold / out steps."""
        if not self.med_end or not self.med_start:
            return 0.0
        total = sum(sec for _, sec in BREATH)
        t = (time.time() - self.med_start) % total
        a, b, c = (sec for _, sec in BREATH)
        if t < a:
            x = t / a
        elif t < a + b:
            return 1.0
        else:
            x = 1 - (t - a - b) / c
        return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, x)))

    def draw_breath_glow(self, p):
        """A soft glowing circle behind her that grows as you breathe in and shrinks as you breathe out."""
        k = self.breath_amount()
        r = 52 + 46 * k
        c = QPointF(110, 150)
        g = QRadialGradient(c, r)
        g.setColorAt(0.0, QColor(214, 200, 255, int(70 + 60 * k)))
        g.setColorAt(0.7, QColor(190, 176, 245, int(40 + 40 * k)))
        g.setColorAt(1.0, QColor(190, 176, 245, 0))
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(c, r, r)
        p.setPen(QPen(QColor(170, 150, 235, int(90 + 80 * k)), 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, r * 0.86, r * 0.86)
        p.restore()

    def draw_zafu(self, p):
        """Her meditation cushion, drawn under her until the 3D pictures arrive."""
        p.save()
        p.setPen(QPen(OUTLINE, 2))
        p.setBrush(QBrush(QColor("#6c5aa8")))
        p.drawRoundedRect(QRectF(52, 212, 116, 26), 12, 12)
        p.setBrush(QBrush(QColor("#7a68b6")))
        p.drawEllipse(QRectF(54, 204, 112, 18))
        p.setPen(QPen(QColor(255, 255, 255, 50), 1.4))
        for x in range(64, 160, 12):
            p.drawLine(QPointF(x, 222), QPointF(x + 2, 236))
        p.restore()

    # ----- calm background sounds -----
    # One simple rule, checked every tick: a sound plays ONLY while you're meditating or while
    # you're listening to a short sample in Customize. Anything else fades it out and stops it.
    def sound_file(self, key):
        path = os.path.join(self.code_dir(), "sounds", key + ".wav")
        return path if os.path.exists(path) else None

    def listen_sample(self, key, secs=5.0):
        """A little sound bite in Customize (call again to stop it early)."""
        now = time.time()
        if now < self.preview_until and self.preview_key == key:
            self.preview_until = 0                 # tapped again: stop
            return False
        self.preview_key = key
        self.preview_start = now
        self.preview_until = now + secs
        return True

    def update_sound(self):
        now = time.time()
        key, level = None, 0.0
        if self.med_end and self.med_sound != "none" and not self.med_asking:
            key = self.med_sound
            level = self.med_volume * min(1.0, (now - (self.med_start or now)) / 3.0)   # 3s fade in
        elif now < self.preview_until and self.preview_key not in (None, "none"):
            key = self.preview_key
            fade_in = min(1.0, (now - self.preview_start) / 0.4)
            fade_out = min(1.0, (self.preview_until - now) / 1.0)
            level = self.med_volume * min(fade_in, fade_out)
        sp = self.sound_player
        if key is None:
            if sp is not None:
                v = sp.volume() - 0.025                    # fade out, then stop for good
                if v <= 0.01:
                    self.kill_sound()
                else:
                    sp.setVolume(v)
            return
        if sp is None or self.sound_key != key:
            self.kill_sound()
            path = self.sound_file(key)
            if not path:
                return
            try:
                from PySide6.QtMultimedia import QSoundEffect
                sp = QSoundEffect(self)
                sp.setSource(QUrl.fromLocalFile(path))
                try:
                    sp.setLoopCount(QSoundEffect.Loop.Infinite.value)
                except Exception:
                    sp.setLoopCount(-2)
                sp.setVolume(0.0)
                sp.play()
                self.sound_player, self.sound_key = sp, key
            except Exception as ex:
                print("sound:", ex, file=sys.stderr, flush=True)
                self.med_sound_broken = True
                return
        v = sp.volume()
        sp.setVolume(v + max(-0.03, min(0.03, level - v)))    # glide toward the level

    def kill_sound(self):
        sp = self.sound_player
        self.sound_player, self.sound_key = None, None
        if sp is not None:
            try:
                sp.stop()
                sp.deleteLater()
            except Exception:
                pass

    CHIMES = {
        # kind: list of (frequency, start second, loudness); soft bell tones
        "start": [(523.25, 0.0, 1.0)],                       # one warm bell to begin
        "middle": [(659.25, 0.0, 0.7)],                      # a lighter single tone halfway
        "end": [(784.0, 0.0, 1.0), (1046.5, 0.35, 1.0)],     # two rising notes to finish
    }

    def play_chime(self, kind="end"):
        """A soft bell (falls back to the system sound). "start" plays the chime you picked."""
        if kind == "start":
            kind = self.med_chime
        if kind == "none":
            return
        shipped = self.sound_file("chime_" + kind)
        if shipped:
            try:
                from PySide6.QtMultimedia import QSoundEffect
                if not hasattr(self, "chimes"):
                    self.chimes = {}
                ch = self.chimes.get("file_" + kind)
                if ch is None:
                    ch = QSoundEffect(self)
                    ch.setSource(QUrl.fromLocalFile(shipped))
                    ch.setVolume(0.7)
                    self.chimes["file_" + kind] = ch
                ch.play()
                return
            except Exception as ex:
                print("chime:", ex, file=sys.stderr, flush=True)
        if kind not in self.CHIMES:
            kind = "start"                       # no file: the built-in soft bell
        try:
            from PySide6.QtMultimedia import QSoundEffect
            import tempfile
            import wave
            import struct
            path = os.path.join(tempfile.gettempdir(), f"digi_chime_{kind}_v2.wav")
            if not os.path.exists(path):
                rate = 44100
                notes = self.CHIMES.get(kind, self.CHIMES["end"])
                length = max(st for _, st, _ in notes) + 2.6
                frames = []
                for i in range(int(rate * length)):
                    t = i / rate
                    v = 0.0
                    for f0, start, loud in notes:
                        if t >= start:
                            tt = t - start
                            env = math.exp(-tt * 2.4) * min(1.0, tt / 0.005)
                            v += loud * env * (math.sin(2 * math.pi * f0 * tt)
                                               + 0.35 * math.sin(2 * math.pi * f0 * 2.76 * tt) * math.exp(-tt * 3)
                                               + 0.15 * math.sin(2 * math.pi * f0 * 5.4 * tt) * math.exp(-tt * 6))
                    frames.append(struct.pack("<h", int(max(-1, min(1, v * 0.2)) * 32767)))
                with wave.open(path, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(rate)
                    w.writeframes(b"".join(frames))
            if not hasattr(self, "chimes"):
                self.chimes = {}
            ch = self.chimes.get(kind)
            if ch is None:
                ch = QSoundEffect(self)
                ch.setSource(QUrl.fromLocalFile(path))
                ch.setVolume(0.6)
                self.chimes[kind] = ch
            ch.play()
        except Exception as ex:
            print("chime:", ex, file=sys.stderr, flush=True)
            QApplication.beep()

    def check_focus(self):
        now = time.time()
        if self.focus_end and now >= self.focus_end:
            self.focus_end = None
            if self.pomo:
                self.break_end = now + POMODORO_BREAK * 60
                self.remind(f"Focus done! {POMODORO_BREAK} minute break~")
            else:
                self.remind("Focus time done! Take a little break~")
        if self.break_end and now >= self.break_end:
            self.break_end = None
            if self.pomo:
                self.focus_end = now + POMODORO_FOCUS * 60
                self.remind("Break's over! Back to focus~")

    # ----- quick reminders -----
    def ask_reminder(self, minutes):
        QTimer.singleShot(50, lambda: self.ask_reminder_now(minutes))

    def ask_reminder_now(self, minutes):
        text, ok = QInputDialog.getText(
            None, "Reminder",
            f"Remind you in {minutes_label(minutes)}. What about?")
        if ok and text.strip():
            self.timers.append([time.time() + minutes * 60,
                                "Reminder: " + text.strip()[:60]])
            self.say("Okay! I'll remind you~", 2000)
            self.happy = 15

    def check_timers(self):
        now = time.time()
        due = [x for x in self.timers if x[0] <= now]
        for item in due:
            self.timers.remove(item)
            self.remind(item[1])

    # ----- eye rest -----
    def check_eye_rest(self):
        now = time.time()
        hour = datetime.now().hour
        if not (self.eye_enabled and EYE_REST_HOURS[0] <= hour < EYE_REST_HOURS[1]):
            self.eye_last = now
            return
        if now - self.eye_last >= EYE_REST_MINUTES * 60 and not self.reminder_active:
            self.eye_last = now
            self.say("Eye break! Look far away for 20 seconds~", 7000)

    # ----- battery -----
    def battery_loop(self):
        while True:
            if HELPER:
                b = W.battery() if W else None
                if b and b != (self.batt_pct, self.on_battery):
                    print(time.strftime("%H:%M:%S"), "battery:", b[0], "%",
                          "(unplugged)" if b[1] else "(charging)", flush=True)
                if b:
                    self.batt_pct, self.on_battery = b
                elif self.batt_pct is None:
                    print(time.strftime("%H:%M:%S"), "battery: couldn't read it", flush=True)
                time.sleep(30)
                continue
            try:
                out = subprocess.run(["pmset", "-g", "batt"], capture_output=True,
                                     text=True, timeout=5).stdout
                if "InternalBattery" in out:
                    m = re.search(r"(\d+)%", out)
                    if m:
                        self.batt_pct = int(m.group(1))
                        self.on_battery = "Battery Power" in out
            except Exception:
                pass
            time.sleep(60)

    def check_battery(self):
        pct = self.batt_pct
        if pct is None or self.reminder_active:
            return
        now = time.time()
        if self.on_battery and pct <= BATTERY_LOW and (
                not self.batt_warned or now - getattr(self, "batt_asked_at", 0) > 600):
            # asks again every 10 minutes until you plug in (and shows a little empty battery)
            self.batt_warned = True
            self.batt_was_low = True
            self.batt_asked_at = now
            self.say(f"Hungry... battery's at {pct}%! Feed me?", 8000)
        elif not self.on_battery and self.batt_was_low:
            self.batt_was_low = False
            self.say("Yum! Thank you for the charge~", 4000)
            self.happy = 30
        if pct > 30:
            self.batt_warned = False

    # ----- welcome back -----
    def is_screen_locked(self):
        if HELPER:
            return W is not None and W.screen_locked()
        if not HAS_QUARTZ:
            return False
        try:
            d = Quartz.CGSessionCopyCurrentDictionary()
            return bool(d and d.get("CGSSessionScreenIsLocked", 0))
        except Exception:
            return False

    def check_welcome(self):
        now = time.time()
        gap = now - self.last_check
        self.last_check = now
        locked = self.is_screen_locked()
        if locked and not self.was_locked:
            self.lock_since = now
        away = None
        if self.was_locked and not locked:
            away = now - (self.lock_since or now)
        self.was_locked = locked
        if away is None and gap > 45:
            away = gap
        if away is not None and away >= 30 and now - self.last_welcome > 20:
            self.last_welcome = now
            self.welcome(away)

    def welcome(self, away):
        if not self.welcome_enabled or self.reminder_active or self.focus_end or self.med_end:
            return
        if away >= 3 * 3600:
            nm = (", " + self.call_name()) if self.call_name() else ""
            self.say(f"Welcome back{nm}! It's been a while~", 4000)
        else:
            self.say(random.choice(WELCOME_LINES), 3500)
        self.happy = 40
        self.jump = 20
        for _ in range(3):
            self.hearts.append([random.randint(80, 140), 90, 0, "\u2665"])

    # ----- steam -----
    def steam_loop(self):
        while True:
            if HELPER:
                try:
                    if W:
                        self.steam_running, self.steam_game = W.steam_state()
                except Exception:
                    pass
                time.sleep(5)
                continue
            try:
                self.steam_running = is_running("steam_osx")
                game = False
                if self.steam_running:
                    out = subprocess.run(["ps", "-axo", "command"],
                                         capture_output=True, text=True,
                                         timeout=5).stdout
                    game = "/steamapps/common/" in out
                self.steam_game = game
            except Exception:
                pass
            time.sleep(5)

    def check_steam(self):
        # video game mode: now and then she tells you how her own game is going
        if (self.gaming and self.corner_settled() and time.time() > self.gaming_cheer
                and not self.msg and not self.reminder_active):
            self.say(random.choice(GAMING_LINES), 2800)
            self.gaming_cheer = time.time() + random.uniform(240, 480)
        steam = self.steam_running
        game = self.steam_game or self.game_mode
        if self.prev_steam is None:
            self.prev_steam, self.prev_game = steam, False
        quiet = ((not self.steam_enabled and not self.game_mode)
                 or self.focus_end or self.sleep_hours or self.reminder_active or self.med_end)
        now = time.time()
        if not quiet:
            if steam and not self.prev_steam and not game:
                self.say(random.choice(STEAM_OPEN_LINES), 3500)
                self.happy = 30
                self.hearts.append([random.randint(80, 140), 90, 0, "\u2665"])
            if game and not self.prev_game:
                self.say("Yay! Have fun!", 3500)
                self.happy = 40
                self.jump = 20
                self.cheer_next = now + random.uniform(240, 480)
                for _ in range(3):
                    self.hearts.append([random.randint(80, 140), 90, 0, "\u2665"])
            elif game and now >= self.cheer_next and not self.msg:
                self.say(random.choice(STEAM_CHEERS), 3000)
                self.happy = 25
                self.cheer_next = now + random.uniform(240, 480)
            if self.prev_game and not game:
                self.say("GG! That was fun!", 3000)
        self.prev_steam, self.prev_game = steam, game

    # ----- greetings -----
    def check_greeting(self):
        key = date.today().strftime("%m-%d")
        if self.greeted == key:
            return
        self.greeted = key
        msg = GREETINGS.get(key)
        party = False
        if self.is_digi_birthday():
            age = date.today().year - DIGI_BORN_YEAR
            msg = (f"It's my birthday!! I'm {age} today! \U0001F382" if age > 0
                   else "It's my birthday!! \U0001F382")
            party = True
        if self.is_my_birthday():
            nm = (", " + self.nickname) if self.nickname else ""
            msg = f"HAPPY BIRTHDAY{nm.upper()}!! \U0001F389\U0001F382 I hope today is amazing!"
            party = True
        if party and not self.reminder_active:
            for _ in range(6):
                self.hearts.append([random.randint(60, 160), 90, 0,
                                    random.choice(["\U0001F389", "\U0001F388", "\u2665"])])
        if msg and not self.reminder_active:
            self.say(msg, 9000)
            self.happy = 60
            self.jump = 20
            for _ in range(5):
                self.hearts.append([random.randint(70, 150), 90, 0, "\u2665"])

    # ----- countdowns -----
    def idle_pool(self):
        lines = list(IDLE_LINES)
        today = date.today()
        for ds, label in COUNTDOWNS:
            try:
                d = datetime.strptime(ds, "%Y-%m-%d").date()
            except Exception:
                continue
            n = (d - today).days
            if n == 0:
                lines.append(f"Today is {label}!")
            elif n == 1:
                lines.append(f"Tomorrow is {label}!")
            elif 1 < n <= 60:
                lines.append(f"{n} days until {label}!")
        for b in self.birthdays:
            n = days_until_birthday(b["month"], b["day"], today)
            if n == 0:
                lines.append(f"It's {b['name']}'s birthday today! \U0001F382")
            elif 1 < n <= 14:
                lines.append(f"{n} days until {b['name']}'s birthday!")
        if self.my_birthday:
            n = days_until_birthday(self.my_birthday["month"], self.my_birthday["day"], today)
            if n == 0:
                lines += ["Happy birthday!! \U0001F382", "It's your special day~ \u2728",
                          "Did you get cake yet? \U0001F370"]
            elif n == 1:
                lines.append("Your birthday is tomorrow!! \U0001F389")
            elif n <= 30:
                lines.append(f"{n} days until your birthday! \U0001F389")
        n = days_until_birthday(*DIGI_BIRTHDAY, today)
        if n == 0:
            lines += ["It's my birthday~ \U0001F382", "Party time! \U0001F389"]
        elif n <= 21:
            lines.append(f"{n} days until my birthday! \U0001F382" if n > 1 else "My birthday is tomorrow!!")
        nxt = dnd_next_game(self.dnd_games, datetime.now()) if self.dnd_games else None
        if nxt:
            offset = (nxt[1].date() - today).days
            if offset == 1:
                lines.append(f"{nxt[0]['title']} is tomorrow!")
            elif 1 < offset <= 4:
                lines.append(f"{offset} days until {nxt[0]['title']}!")
        if self.todos:
            n = len(self.todos)
            lines.append("1 task left on your list!" if n == 1
                         else f"{n} tasks left on your list!")
        return lines

    def pick_direction(self):
        angle = random.uniform(0, 2 * math.pi)
        self.vx = math.cos(angle) * SPEED
        self.vy = math.sin(angle) * SPEED * 0.5

    def is_my_birthday(self, today=None):
        b = self.my_birthday
        return bool(b) and days_until_birthday(b["month"], b["day"], today) == 0

    def is_digi_birthday(self, today=None):
        return days_until_birthday(*DIGI_BIRTHDAY, today) == 0

    def birthday_news(self, today=None):
        """(sticky reminder for today's birthdays, heads-up line for upcoming ones)."""
        today = today or date.today()
        todays, soon = [], []
        for b in self.birthdays:
            n = days_until_birthday(b["month"], b["day"], today)
            if n == 0:
                todays.append(b["name"])
            elif n in BDAY_HEADS_UP:
                soon.append((n, b["name"]))
        rem = None
        if todays:
            who = todays[0] if len(todays) == 1 else ", ".join(todays[:-1]) + " and " + todays[-1]
            rem = f"Today is {who}'s birthday! \U0001F382 Don't forget to wish them a happy birthday!"
        line = None
        if soon:
            n, name = min(soon)
            if n == 1:
                line = f"Psst! {name}'s birthday is tomorrow! \U0001F381"
            else:
                line = f"{name}'s birthday is in a week! Maybe think about a card or gift? \U0001F381"
        return rem, line

    def check_birthdays(self):
        now = datetime.now()
        key = now.strftime("%Y-%m-%d")
        if self.bday_checked == key or now.hour < BDAY_TIME or self.sleep_hours:
            return
        if self.reminder_active or self.msg:
            return                          # wait until she's not saying something else
        self.bday_checked = key
        rem, line = self.birthday_news(now.date())
        if rem and line:
            rem += "  " + line
        if rem:
            self.remind(rem)
            for _ in range(4):
                self.hearts.append([random.randint(70, 150), 90, 0, "\u2665"])
        elif line:
            self.say(line, 7000)
            self.happy = 20

    # ---------- D&D ----------
    def dnd_sync_days(self):
        """dnd_days (used for the countdown and solo play) = every day that has a game."""
        if self.dnd_games:
            self.dnd_days = [d for d in DAY_ORDER if any(d in g["days"] for g in self.dnd_games)]

    def dnd_now(self):
        """(game, start, end) if one of your games is on right now (checked every few seconds)."""
        t = time.time()
        if t - self.dnd_cache[0] > 5:
            self.dnd_cache = (t, dnd_session_at(self.dnd_games, datetime.now()))
        return self.dnd_cache[1]

    def dnd_changed(self):
        self.dnd_sync_days()
        self.dnd_cache = (0.0, None)
        self.save_custom()
        nw = getattr(self, "notes_win", None)
        if nw is not None:
            if self.dnd_games:
                nw.refresh()
            else:
                nw.close()

    def call_name(self):
        """What she calls you: your table name during a game (if you want), else your nickname."""
        s = self.dnd_now()
        if s and self.dnd_opts.get("use_name", True):
            g = s[0]
            if g["char"]:
                return g["char"]
            if g["role"] == "dm":
                return gm_title(g)
        return getattr(self, "nickname", "")

    def check_dnd(self):
        if not self.dnd_games or getattr(self, "intro_step", -1) >= 0:
            return
        now = datetime.now()
        cur = self.dnd_now()
        if cur:
            g, st, end = cur
            key = (st, g["title"], "start")
            if key not in self.dnd_said and now - st < timedelta(minutes=15):
                self.dnd_said.add(key)
                name = self.call_name() or (gm_title(g) if g["role"] == "dm" else "adventurer")
                lines = DND_DM_LINES if g["role"] == "dm" else DND_START_LINES
                if not self.reminder_active:
                    self.say(random.choice(lines).format(name=name, title=g["title"]), 5000)
                    self.happy = 40
                    self.jump = 20
            self.dnd_last = (g, st, end)
            return
        last = getattr(self, "dnd_last", None)
        if last:                                  # a game just ended
            self.dnd_last = None
            g, st, end = last
            key = (st, g["title"], "end")
            if key not in self.dnd_said and now - end < timedelta(minutes=10):
                self.dnd_said.add(key)
                name = g["char"] if (g["char"] and self.dnd_opts.get("use_name", True)) else self.nickname
                if not self.reminder_active:
                    self.say(random.choice(DND_END_LINES).format(name=name or "friend"), 5000)
        nxt = dnd_next_game(self.dnd_games, now)
        if nxt:
            g, st = nxt
            key = (st, g["title"], "soon")
            if key not in self.dnd_said and timedelta(0) < st - now <= timedelta(minutes=DND_HEADS_UP):
                self.dnd_said.add(key)
                mins = max(1, int((st - now).total_seconds() // 60))
                if not self.reminder_active:
                    self.say(f"{g['title']} starts in {mins} minutes! Dice ready? \U0001F3B2", 5000)

    def open_dnd_notes(self, index=None):
        """The pop-out notes window (opens on the game that's on now, if there is one)."""
        if not self.dnd_games:
            self.say("Add a game first, then you can take notes for it~ \U0001F4DC", 3000)
            self.open_customize(4)
            return
        if index is None or index < 0:
            cur = self.dnd_now()
            index = self.dnd_games.index(cur[0]) if cur and cur[0] in self.dnd_games else 0
        if getattr(self, "notes_win", None) is None:
            self.notes_win = DndNotesWindow(self)
        self.notes_win.refresh(index)
        self.notes_win.show()
        self.notes_win.raise_()
        self.notes_win.activateWindow()

    def export_dnd_notes(self, parent=None, index=None):
        """Save one game's notes (or all of them) to a text file you pick."""
        games = self.dnd_games if index is None else self.dnd_games[index:index + 1]
        if not games:
            self.say("No notes to save yet~", 2500)
            return
        base = "Game night notes" if index is None else (re.sub(r'[\\/:*?"<>|]', "", games[0]["title"]).strip()
                                                        or "Game night") + " notes"
        folder = os.path.expanduser("~/Documents")
        if not os.path.isdir(folder):
            folder = os.path.expanduser("~")
        path, _ = QFileDialog.getSaveFileName(parent, "Save your game night notes",
                                              os.path.join(folder, base + ".txt"),
                                              "Text file (*.txt);;Markdown (*.md)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(dnd_notes_text(games))
        except Exception as ex:
            QMessageBox.warning(parent, "Couldn't save", f"I couldn't save the notes there:\n{ex}")
            return
        self.say(f"Saved! Your notes are in {os.path.basename(path)} \U0001F4DC", 3500)

    def dnd_notes_set(self, i, text, source=None):
        """Notes typed in the D&D tab or the pop-out: kept, saved a moment later, shown in both."""
        self.dnd_games[i]["notes"] = text[:20000]
        if getattr(self, "notes_save", None) is None:
            self.notes_save = QTimer(self)
            self.notes_save.setSingleShot(True)
            self.notes_save.setInterval(1200)
            self.notes_save.timeout.connect(self.save_custom)
        self.notes_save.start()
        nw = getattr(self, "notes_win", None)
        if nw is not None and nw is not source and nw.isVisible() and nw.game.currentIndex() == i:
            nw.load()
        cw = self.custom_win
        if cw is not None and cw is not source and hasattr(cw, "notes_game") and cw.notes_game.currentIndex() == i:
            cw.notes_show()

    def dnd_place_later(self):
        """The notes window moved or changed size: remember it once it settles."""
        if getattr(self, "notes_place", None) is None:
            self.notes_place = QTimer(self)
            self.notes_place.setSingleShot(True)
            self.notes_place.setInterval(1500)
            self.notes_place.timeout.connect(lambda: self.notes_win.remember_place()
                                             if getattr(self, "notes_win", None) else None)
        self.notes_place.start()

    def dnd_views_refresh(self):
        """Initiative changed: update the D&D tab and the pop-out."""
        nw = getattr(self, "notes_win", None)
        if nw is not None:
            nw.refresh_init()
        cw = self.custom_win
        if cw is not None and hasattr(cw, "init_list"):
            cw.refresh_init()

    def dnd_turn_name(self):
        o = self.dnd_init["order"]
        return o[self.dnd_init["turn"] % len(o)][0] if o else None

    def dnd_next_turn(self):
        o = self.dnd_init["order"]
        if not o:
            self.say("Nobody's in initiative yet! Add them in Customize \u2192 Game night~", 3000)
            return
        self.dnd_init["turn"] += 1
        if self.dnd_init["turn"] >= len(o):
            self.dnd_init["turn"] = 0
            self.dnd_init["round"] += 1
        self.save_custom()
        self.dnd_views_refresh()
        self.dnd_announce_turn()

    def my_char_names(self):
        return {g["char"].lower() for g in self.dnd_games if g["char"] and g["role"] != "dm"}

    def my_char_name(self):
        """Your character in the game that's on now (or your first character)."""
        s = self.dnd_now()
        if s and s[0]["char"] and s[0]["role"] != "dm":
            return s[0]["char"]
        return next((g["char"] for g in self.dnd_games if g["char"] and g["role"] != "dm"), "")

    def dnd_announce_turn(self):
        who = self.dnd_turn_name()
        if not who:
            return
        o = self.dnd_init["order"]
        mine = self.my_char_names()
        nxt = o[(self.dnd_init["turn"] + 1) % len(o)][0] if len(o) > 1 else None
        up_next = nxt is not None and nxt.lower() in mine and who.lower() not in mine
        rnd = self.dnd_init["round"]
        if who.lower() in mine:
            self.say(f"Your turn, {who}! You've got this! \u2694\ufe0f", 3500)
            self.happy = 30
        elif up_next:
            self.say(f"{who}'s turn! You're up next, {nxt}~ get ready! \U0001F3B2", 3500)
        elif self.dnd_init["turn"] == 0:
            self.say(f"Round {rnd}! {who} goes first~", 3000)
        else:
            self.say(f"{who}'s turn!", 2500)

    def check_reminders(self):
        self.check_birthdays()
        self.check_cycle()
        self.check_dnd()
        now = datetime.now()
        key = now.strftime("%H:%M")
        today = now.strftime("%Y-%m-%d")
        for item in self.reminders:
            when, text = item[0], item[1]
            days = item[2] if len(item) > 2 else None
            if days is not None:
                allowed = [DAY_NUMBERS[d] for d in days]
                if now.weekday() not in allowed:
                    continue
            if when == key and (today, when, text) not in self.fired:
                self.fired.add((today, when, text))
                self.remind(text)

    # ---------- music (runs in the background) ----------
    def run_osascript(self, script):
        try:
            r = subprocess.run(["osascript", "-e", script],
                               capture_output=True, text=True, timeout=6)
            return r.stdout.strip(), r.stderr.strip()
        except Exception:
            return "", ""

    def music_loop(self):
        while True:
            if HELPER:
                self.music_playing = bool(W.media_playing()) if W else False
                time.sleep(4)
                continue
            playing = False

            for app in PLAYER_APPS:
                if is_running(app):
                    out, _ = self.run_osascript(PLAYER_SCRIPT.replace("APPNAME", app))
                    if out == "playing":
                        playing = True
                        break

            if not playing:
                for br in CHROMIUM_BROWSERS:
                    if is_running(br):
                        script = (CHROMIUM_SCRIPT.replace("APPNAME", br)
                                  .replace("JSCODE", JS_CHECK))
                        out, err = self.run_osascript(script)
                        if out == "playing":
                            playing = True
                            break
                        if "JavaScript" in err or "Apple Events" in err:
                            self.js_error = True

            if not playing and is_running("Safari"):
                script = SAFARI_SCRIPT.replace("JSCODE", JS_CHECK)
                out, err = self.run_osascript(script)
                if out == "playing":
                    playing = True
                if "JavaScript" in err or "Apple Events" in err:
                    self.js_error = True

            self.music_playing = playing
            time.sleep(4)

    # ---------- app reactions ----------
    def check_app(self):
        if not ((HAS_APPKIT or (HELPER and W)) and self.react_enabled):
            return
        if self.focus_end or self.sleep_hours or self.med_end:
            return
        try:
            if HELPER:
                name = W.front_app_name()
            else:
                name = NSWorkspace.sharedWorkspace().frontmostApplication().localizedName()
        except Exception:
            return
        if name == self.last_app:
            return
        self.last_app = name
        msg = APP_REACTIONS.get(name)
        if not msg or self.reminder_active:
            return
        now = time.time()
        if now - self.app_last.get(name, 0) < 120:
            return
        self.app_last[name] = now
        self.say(msg, 3500)
        self.happy = 30
        self.hearts.append([random.randint(80, 140), 90, 0, "\u2665"])

    # ---------- windows ----------
    def get_front_window(self):
        if HELPER:
            if W is None:
                return None
            # Windows gives real pixels; Qt works in scaled ones (e.g. 150% display scaling)
            scr = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
            dpr = scr.devicePixelRatio() if scr else 1.0
            for x, y, w, h in W.windows_front_to_back(os.getpid()):
                rect = QRect(int(x / dpr), int(y / dpr), int(w / dpr), int(h / dpr))
                if rect.width() < 300 or rect.height() < 200:
                    continue
                if not rect.intersects(self.area):
                    continue
                return rect
            return None
        if not HAS_QUARTZ:
            return None
        try:
            infos = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionOnScreenOnly
                | Quartz.kCGWindowListExcludeDesktopElements,
                Quartz.kCGNullWindowID)
        except Exception:
            return None
        my_pid = os.getpid()
        for w in infos or []:
            try:
                if w.get(Quartz.kCGWindowLayer, 1) != 0:
                    continue
                if w.get(Quartz.kCGWindowOwnerPID) == my_pid:
                    continue
                if w.get(Quartz.kCGWindowOwnerName) in SKIP_OWNERS:
                    continue
                if w.get(Quartz.kCGWindowAlpha, 1.0) < 0.1:
                    continue
                b = w.get(Quartz.kCGWindowBounds)
                if not b:
                    continue
                rect = QRect(int(b["X"]), int(b["Y"]),
                             int(b["Width"]), int(b["Height"]))
                if rect.width() < 300 or rect.height() < 200:
                    continue
                if not rect.intersects(self.area):
                    continue
                return rect
            except Exception:
                continue
        return None

    def can_perch(self, w):
        return w.top() - 221 >= self.area.top()

    def can_peek(self, w, side):
        if side == "top":
            return w.top() >= self.area.top() + 160
        if side == "right":
            return w.right() <= self.area.right() - 90
        if side == "left":
            return w.left() >= self.area.left() + 90
        return False

    def set_mode(self, mode, secs):
        self.peek_ready = False
        if self.sitting:
            self.sitting = False
            if self.cur_window is not None:
                self.py = float(self.cur_window.top() - 221)
        self.mode = mode
        self.mode_until = time.time() + secs
        self.pause = 0
        self.jump = 0
        if mode == "peek" and self.cur_window is not None:
            self.clip_rect = self.cur_window
        else:
            self.clip_rect = None

    def choose_next_mode(self, win):
        options = []
        if self.follow_enabled:
            options.append("follow")
        sides = []
        if win is not None:
            if self.can_perch(win):
                options.append("perch")
            sides = [s for s in ("top", "right", "left") if self.can_peek(win, s)]
            if sides:
                options.append("peek")
        if not options:
            self.set_mode("wander", random.uniform(10, 25))
            return
        pick = random.choice(options)
        if pick == "follow":
            self.set_mode("follow", random.uniform(8, 14))
            self.say("Coming~", 1500)
        elif pick == "perch":
            self.set_mode("perch", random.uniform(15, 30))
            self.pdir = random.choice([-1, 1])
            self.say("Hop hop!", 1500)
        else:
            self.peek_side = random.choice(sides)
            if self.peek_side == "top":
                lo = win.left() - 40 + 20
                hi = win.right() - 180 - 20
                if hi < lo:
                    lo = hi = win.center().x() - 110
                self.peek_x = random.randint(int(lo), int(hi))
            self.set_mode("peek", random.uniform(10, 20))

    def check_mode(self):
        now = time.time()
        blocked = (self.focus_end or self.sleep_hours or self.reminder_active or self.med_end
                   or self.med_asking or self.intro_step >= 0 or not self.wander
                   or self.dragging or self.streaming
                   or self.ball is not None or self.falling)
        win = None
        if self.windows_enabled and HAS_WINLIST:
            win = self.get_front_window()
        self.cur_window = win

        if blocked:
            if self.mode != "wander":
                self.set_mode("wander", 15)
            return

        if self.mode == "perch" and (win is None or not self.can_perch(win)):
            self.set_mode("wander", random.uniform(10, 20))
            return
        if self.mode == "peek":
            if win is None or not self.can_peek(win, self.peek_side):
                self.set_mode("wander", random.uniform(10, 20))
                return
            self.clip_rect = win

        if now >= self.mode_until:
            if self.mode == "wander":
                self.choose_next_mode(win)
            else:
                if self.mode == "peek":
                    self.say("Peekaboo!", 1800)
                    self.happy = 25
                self.set_mode("wander", random.uniform(10, 25))

    # ---------- movement ----------
    def clamp_pos(self, x, y):
        min_x = self.area.left() - 40
        max_x = self.area.right() - 180
        min_y = self.area.top()
        max_y = self.area.bottom() - 230
        return max(min_x, min(max_x, x)), max(min_y, min(max_y, y))

    def glide(self, tx, ty, speed):
        dx = tx - self.px
        dy = ty - self.py
        dist = math.hypot(dx, dy)
        if dist < 2:
            self.px, self.py = float(tx), float(ty)
            self.move(int(self.px), int(self.py))
            return True
        step = min(dist, speed)
        self.px += dx / dist * step
        self.py += dy / dist * step
        self.walking = True
        self.move(int(self.px), int(self.py))
        return False

    def do_wander(self):
        if self.pause > 0:
            self.pause -= 1
            return
        if random.random() < PAUSE_CHANCE:
            self.pause = random.randint(40, 150)
            self.pick_direction()
            return

        self.walking = True
        self.px += self.vx
        self.py += self.vy

        min_x = self.area.left() - 40
        max_x = self.area.right() - 180
        min_y = self.area.top()
        max_y = self.area.bottom() - 230
        if self.px < min_x:
            self.px = min_x
            self.vx = abs(self.vx)
        if self.px > max_x:
            self.px = max_x
            self.vx = -abs(self.vx)
        if self.py < min_y:
            self.py = min_y
            self.vy = abs(self.vy)
        if self.py > max_y:
            self.py = max_y
            self.vy = -abs(self.vy)
        self.move(int(self.px), int(self.py))

    def do_follow(self):
        cp = QCursor.pos()
        side = 1 if cp.x() < self.area.center().x() else -1
        tx = cp.x() + side * 150 - 110
        ty = cp.y() + 60 - 157
        gx, gy = self.clamp_pos(tx, ty)
        dist = math.hypot(gx - self.px, gy - self.py)
        self.glide(gx, gy, min(6.0, max(1.5, dist * 0.06)))

    def do_perch(self):
        w = self.cur_window
        if w is None:
            return
        ty = w.top() - (SIT_OFFSET if self.sitting else 221)
        min_x = w.left() - 40
        max_x = w.right() - 180
        if max_x < min_x:
            min_x = max_x = w.center().x() - 110
        if abs(self.py - ty) > 3 and not self.sitting:
            tx = max(min_x, min(max_x, self.px))
            gx, gy = self.clamp_pos(tx, ty)
            self.glide(gx, gy, 6.0)
            return
        self.py = float(ty)
        if self.sitting:
            if time.time() > self.sit_until:
                self.sitting = False          # stand back up
                self.py = float(w.top() - 221)
                self.jump = 12
            self.px = max(min_x, min(max_x, self.px))
            self.move(int(self.px), int(self.py))
            return
        if "sit" in self.frames and (self.want_sit or random.random() < 0.004):
            self.sitting = True
            self.py = float(w.top() - SIT_OFFSET)
            self.move(int(self.px), int(self.py))
            self.sit_until = time.time() + (30 if self.want_sit else random.uniform(10, 25))
            self.want_sit = False
            if not self.reminder_active and random.random() < 0.5:
                self.say(random.choice(["*kicks feet*", "Nice view up here~", "Just sitting~"]), 1800)
            return
        if self.pause > 0:
            self.pause -= 1
            return
        if random.random() < 0.006:
            self.pause = random.randint(30, 90)
            return
        if self.jump == 0 and random.random() < 0.012:
            self.jump = 20
        self.walking = True
        self.px += self.pdir * 1.6
        if self.px < min_x:
            self.px = float(min_x)
            self.pdir = 1
        if self.px > max_x:
            self.px = float(max_x)
            self.pdir = -1
        self.move(int(self.px), int(self.py))

    def do_peek(self):
        w = self.cur_window
        if w is None or self.peek_side is None:
            return
        new = any(("peektop" if self.peek_side == "top" else "peekside") == k for k in self.frames)
        if self.peek_side == "top":
            tx = max(w.left() - 40, min(w.right() - 180, self.peek_x))
            ty = w.top() - (112 if new else 158)
        elif self.peek_side == "right":
            tx = w.right() - (96 if new else 90)
            ty = w.center().y() - (98 if new else 157)
        else:
            tx = w.left() - (124 if new else 130)
            ty = w.center().y() - (98 if new else 157)
        gx, gy = self.clamp_pos(tx, ty)
        if self.peek_ready:
            # already in place: follow the window if it moves, no walking
            self.px, self.py = float(gx), float(gy)
            self.move(int(self.px), int(self.py))
        elif self.glide(gx, gy, 5.0):
            self.peek_ready = True          # arrived: now grab the edge

    def move_pet(self):
        self.walking = False
        if self.dragging or self.falling or self.bed:
            return
        if self.teleport is not None:
            return
        if self.pose_now() and not self.activity:
            return
        if self.med_asking or self.intro_step >= 0:      # asking you something: in the middle
            tx = self.area.center().x() - 110
            ty = self.area.center().y() - 120
            if abs(self.px - tx) > 2 or abs(self.py - ty) > 2:
                self.glide(tx, ty, 6.0)
            return
        if self.med_end:
            return                              # she stays put on her cushion
        if self.menu_open or self.rps_busy or self.trivia_busy:
            return                              # her menu is open (or a game): hold still
        if self.choice_bar is not None:
            limit = getattr(self, "choice_timeout", None)
            if limit and time.time() - self.choice_since > limit:
                pick = self.choice_pick         # buttons left alone: put them away ("close")
                self.close_choices()
                pick("close")
            else:
                return                          # buttons under her: hold still so you can click them
        if self.activity:
            self.do_activity_move()
            return
        if self.streaming and not self.reminder_active:
            self.do_stream_corner()
            return
        if self.ball and not self.reminder_active and not self.focus_end:
            self.do_chase()
            return
        if time.time() < self.shoo_until and self.shoo_target:
            tx, ty = self.shoo_target
            if abs(self.px - tx) > 2 or abs(self.py - ty) > 2:
                self.glide(tx, ty, 7.0)
            return
        if (self.dragging or self.happy or self.reminder_active
                or not self.wander or self.sleepy or self.hovering
                or self.focus_end):
            return
        if self.mode == "follow":
            self.do_follow()
        elif self.mode == "perch":
            self.do_perch()
        elif self.mode == "peek":
            self.do_peek()
        else:
            self.do_wander()

    def tick(self):
        self.t += 1
        # every 2 seconds: still floating on top? (not while her menu is open: putting her window
        # back in front closes an open menu on a Mac)
        if IS_MAC and self.t % 50 == 1 and not self.menu_open:
            for w in (self, self.bubble_win, self.choice_bar):
                mac_keep_floating(w)
        try:
            if self.bubble_win is None:
                self.bubble_win = BubbleWin(self)
            self.bubble_win.follow()
            if self.choice_bar is not None:
                self.choice_bar.follow()
            self.update_sound()
        except Exception as ex:
            print("bubble:", ex, file=sys.stderr, flush=True)

        if self.happy > 0:
            self.happy -= 1
        if self.jump > 0:
            self.jump -= 1

        if self.kick_cd > 0:
            self.kick_cd -= 1
        if self.dice:
            self.update_dice()
        if self.bomb:
            self.update_bomb()
        self.fun_tick()
        if self.activity or self.card or self.snack or self.castle:
            self.activity_tick()
        if self.ears is not None:
            self.voice_tick()
        if self.falling and not self.dragging:
            self.update_fall()
        if self.ball:
            self.ball.step()
            if time.time() > self.ball_until or self.kicks >= 10:
                self.end_ball()
        if self.t % 125 == 0:
            self.update_stream()

        # being held: surprised first, then she goes limp and dangles
        if self.dragging and self.moved:
            self.held_ticks += 1
            if self.held_ticks == 12:
                self.surprised = False
            if self.held_ticks % 110 == 0 and not self.reminder_active:
                self.say(random.choice(HELD_LINES), 1800)
        self.swing_v += -0.12 * self.swing      # spring back to hanging straight
        self.swing_v *= 0.90                    # air friction
        self.swing += self.swing_v
        self.swing = max(-35.0, min(35.0, self.swing))
        if self.pad_x and not self.dragging and abs(self.swing) < 1.0 and abs(self.swing_v) < 0.5:
            self.set_swing_room(False)
        if not self.dragging and abs(self.swing) < 0.05 and abs(self.swing_v) < 0.05:
            self.swing = self.swing_v = 0.0

        # blinking
        if self.blink:
            self.blink_len -= 1
            if self.blink_len <= 0:
                self.blink = False
        else:
            self.blink_cd -= 1
            if self.blink_cd <= 0:
                self.blink = True
                self.blink_len = 4
                self.blink_cd = random.randint(60, 150)

        # speech bubble timer
        if self.msg_ticks > 0:
            self.msg_ticks -= 1
            if self.msg_ticks == 0:
                self.msg = None
                self.reminder_active = False

        # petting: hold the mouse over her for a moment
        if self.hovering and not self.dragging:
            self.hover_ticks += 1
        else:
            self.hover_ticks = 0
        was_petting = self.petting
        self.petting = self.hover_ticks > 50 and not self.reminder_active
        if self.petting and not was_petting:
            self.say("mmm~" if self.sleepy else "purr~", 2000)
            now_t = time.time()
            self.pat_times = [x for x in self.pat_times if now_t - x < 60] + [now_t]
            if len(self.pat_times) >= 3 and not self.sleepy:
                self.get_shy()
        if self.petting and self.hover_ticks == 50 + 25 * 8 and not self.sleepy:
            self.get_shy()                       # eight seconds of petting is a lot!
        if self.petting and self.t % 35 == 0:
            self.hearts.append([random.randint(80, 140), 90, 0, "\u2665"])

        # one-time hint if the browser setting is still off
        if self.js_error and not self.js_warned and not self.reminder_active:
            self.js_warned = True
            self.say("I can't hear your browser yet! Check the setup~", 6000)

        # singing along to music
        self.singing = (self.music_playing and self.sing_enabled) or time.time() < self.sing_until
        if self.singing and not self.was_singing:
            if not self.reminder_active:
                self.say("la la la~", 2500)
            self.sing_cd = 60
        if self.was_singing and not self.singing and not self.reminder_active:
            self.say("Aww, song's over!", 2000)
            self.happy = 20
        self.was_singing = self.singing

        if self.singing:
            self.sing_cd -= 1
            if self.sing_cd <= 0:
                if not self.reminder_active:
                    self.say(random.choice(SING_LINES), 1800)
                self.hearts.append([random.randint(70, 150), 90, 0,
                                    random.choice(["\u266a", "\u266b"])])
                self.sing_cd = random.randint(60, 100)

        # sleepy?
        self.sleepy = (self.sleep_hours and not self.reminder_active
                       and not self.singing and not self.happy
                       and not self.dragging and not self.petting
                       and not self.surprised)
        self.update_bed()

        # idle chatter
        if not self.menu_open:
            self.idle_cd -= 1
        if self.idle_cd <= 0:
            if (not self.msg and not self.happy and not self.singing
                    and not self.sleepy and not self.focus_end
                    and not self.streaming and not self.med_end):
                if not self.activity and random.random() < 0.4 and self.pick_idle_fun():
                    pass
                else:
                    self.say(random.choice(self.idle_pool()))
            self.idle_cd = random.randint(500, 1000)

        # once-per-second checks
        if self.t % 25 == 0:
            self.sleep_hours = in_sleep_hours() or time.time() < self.nap_until
            self.check_welcome()
            self.check_greeting()
            self.check_reminders()
            self.check_dnd_mode()
            self.check_timers()
            self.check_focus()
            self.check_meditation()
            self.check_med_invite()
            self.check_eye_rest()
            self.check_battery()
            self.update_tick()
            self.update_progress_tick()
            if self.t % (25 * 86400) == 25 * 90:      # 90 seconds after she starts, then daily
                self.check_updates()
            self.check_steam()
            self.check_app()
            self.check_mode()

        for h in self.hearts:
            h[1] -= 2
            h[2] += 1
        self.hearts = [h for h in self.hearts if h[2] < 30]

        self.move_pet()
        self.update()

    # ---------- drawing ----------
    def draw_accessory(self, p, b, acc):
        if acc == "hat":
            p.setPen(QPen(QColor("#c0392b"), 2))
            p.setBrush(QBrush(QColor("#e74c3c")))
            p.drawPolygon(QPolygonF([QPointF(78, 98 + b), QPointF(142, 98 + b),
                                     QPointF(122, 50 + b)]))
            p.setPen(QPen(QColor("#dddddd"), 2))
            p.setBrush(QBrush(QColor("white")))
            p.drawRoundedRect(QRectF(74, 92 + b, 72, 12), 6, 6)
            p.drawEllipse(QPointF(122, 50 + b), 7, 7)
        elif acc == "flower":
            p.setPen(QPen(QColor("#e58fb0"), 1))
            p.setBrush(QBrush(QColor("#ffb3d1")))
            for i in range(5):
                ang = math.radians(i * 72)
                p.drawEllipse(QPointF(78 + 6 * math.cos(ang),
                                      88 + b + 6 * math.sin(ang)), 4.5, 4.5)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor("#ffd54f")))
            p.drawEllipse(QPointF(78, 88 + b), 3.5, 3.5)
        elif acc == "scarf":
            p.setPen(QPen(QColor("#c0392b"), 2))
            p.setBrush(QBrush(QColor("#e8636f")))
            p.drawRoundedRect(QRectF(58, 184 + b, 104, 16), 8, 8)
            p.drawRoundedRect(QRectF(128, 194 + b, 16, 30), 6, 6)

    def head_anchor(self, pm):
        """Where the top-middle of her head is in this picture (cached): (x, y) in its pixels."""
        cache = self.__dict__.setdefault("anchor_cache", {})
        key = pm.cacheKey()
        if key in cache:
            return cache[key]
        img = pm.toImage().scaled(pm.width() // 4, pm.height() // 4)
        w, h = img.width(), img.height()
        top, xs = None, []
        for y in range(h):
            row = [x for x in range(int(w * 0.2), int(w * 0.8)) if img.pixelColor(x, y).alpha() > 140]
            if row:
                if top is None:
                    top = y
                xs += row
                if y - top >= h * 0.08:
                    break
        res = None if top is None else ((sum(xs) / len(xs)) * 4 + 2, top * 4)
        if len(cache) > 400:
            cache.clear()
        cache[key] = res
        return res

    def draw_hand_item(self, p, b, acc, dark):
        """Drawn book / sword in her hand (her mittens are at about (73, 168) and (147, 168))."""
        p.save()
        p.setPen(QPen(dark, 1.3))
        if acc == "book":
            p.translate(73, 166 + b)
            p.rotate(-8)
            p.setBrush(QBrush(QColor("#fff3dc")))
            p.drawRect(QRectF(-10, -31, 23, 28))                           # pages peeking out
            p.setBrush(QBrush(QColor("#5e3d8f")))
            p.drawRoundedRect(QRectF(-12, -32, 23, 30), 2, 2)              # cover
            p.setBrush(QBrush(QColor("#462c6e")))
            p.drawRect(QRectF(-12, -32, 3, 30))                            # spine
            p.setPen(QPen(QColor("#f2c14e"), 0.9))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(-7.5, -29.5, 16, 25))                        # gold border
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor("#f2c14e")))
            pts = [(90, 70), (85, 76), (71, 82), (61, 91), (64, 74), (54, 59), (52, 88), (55, 100),
                   (30, 93), (30, 76), (14, 80), (35, 55), (22, 45), (5, 31), (15, 16), (25, 18),
                   (14, 28), (29, 38), (28, 24), (39, 30), (64, 25), (63, 41), (73, 60), (86, 66)]
            p.drawPolygon(QPolygonF([QPointF(0.5 + (x - 47.5) * 0.17, -17 - (y - 58) * 0.17)
                                     for x, y in pts]))                    # the dragon
            p.setBrush(QBrush(QColor("#ff7eb6")))
            p.drawPolygon(QPolygonF([QPointF(5, -3), QPointF(7.5, -3), QPointF(7.5, 5),
                                     QPointF(6.2, 3.5), QPointF(5, 5)]))   # ribbon bookmark
        else:
            p.translate(147, 168 + b)
            p.rotate(28)
            p.setBrush(QBrush(QColor("#e3e9f2")))
            p.drawPolygon(QPolygonF([QPointF(-3, -9), QPointF(3, -9), QPointF(3, -38),
                                     QPointF(0, -45), QPointF(-3, -38)]))  # blade
            p.setPen(QPen(QColor("#b7c6e4"), 1.2))
            p.drawLine(QPointF(0, -12), QPointF(0, -36))
            p.setPen(QPen(dark, 1.3))
            p.setBrush(QBrush(QColor("#6b5fb5")))
            p.drawRoundedRect(QRectF(-2, -7, 4, 12), 1.5, 1.5)             # grip
            p.setBrush(QBrush(QColor("#f2c14e")))
            p.drawRoundedRect(QRectF(-9, -10, 18, 4), 2, 2)                # crossguard
            p.drawEllipse(QPointF(0, 7), 2.8, 2.8)                         # pommel
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor("#ff7eb6")))
            p.drawEllipse(QPointF(0, -8), 1.6, 1.6)                        # gem
        p.restore()

    def draw_pinned_accessory(self, p, pm, target, acc):
        """A drawn outfit, moved to wherever her head is in this picture (it follows every pose)."""
        here = self.head_anchor(pm)
        ref_pm = (self.frames.get("idle") or [None])[0]
        ref = self.head_anchor(ref_pm) if ref_pm is not None else None
        if here is None or ref is None:
            self.draw_accessory_3d(p, int(target.y() - 38), acc)
            return
        sx = target.width() / pm.width()
        sy = target.height() / pm.height()
        ref_extra = (ref_pm.height() - 480) * 0.431
        rx = 15 + ref[0] * 190 / ref_pm.width()
        ry = 38 - ref_extra + ref[1] * (207 + ref_extra) / ref_pm.height()
        nx = target.x() + here[0] * sx
        ny = target.y() + here[1] * sy
        p.save()
        p.translate(nx - rx, ny - ry)
        self.draw_accessory_3d(p, 0, acc)
        p.restore()

    def draw_accessory_3d(self, p, b, acc):
        """Outfits sized for her 3D body (head center ~ (110, 90), neck ~ y 131)."""
        dark = QColor("#1b1b1b")
        if acc in HAND_ACCS:
            self.draw_hand_item(p, b, acc, dark)
            return
        if acc == "witch":
            p.setPen(QPen(dark, 2))
            p.setBrush(QBrush(QColor("#2e2342")))
            p.drawEllipse(QPointF(110, 56 + b), 62, 9)
            p.drawPolygon(QPolygonF([QPointF(80, 55 + b), QPointF(140, 55 + b),
                                     QPointF(128, 24 + b), QPointF(136, 5 + b),
                                     QPointF(114, 20 + b)]))
            p.setBrush(QBrush(QColor("#f0a030")))
            p.drawRect(QRectF(82, 46 + b, 56, 8))
        elif acc == "ears":
            for sgn in (-1, 1):
                ox = lambda x: 110 + sgn * (x - 110)
                p.setPen(QPen(dark, 2))
                p.setBrush(QBrush(QColor("#8a7fc2")))
                p.drawPolygon(QPolygonF([QPointF(ox(76), 60 + b), QPointF(ox(102), 50 + b),
                                         QPointF(ox(82), 26 + b)]))
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor("#ffb3c8")))
                p.drawPolygon(QPolygonF([QPointF(ox(82), 55 + b), QPointF(ox(96), 50 + b),
                                         QPointF(ox(85), 36 + b)]))
        if acc in ("hat", "santa"):
            b += 8
            p.setPen(QPen(dark, 2))
            p.setBrush(QBrush(QColor("#e0393e")))
            hat = QPolygonF([QPointF(72, 52 + b), QPointF(146, 50 + b),
                             QPointF(150, 30 + b), QPointF(162, 14 + b),
                             QPointF(128, 22 + b), QPointF(96, 30 + b)])
            p.drawPolygon(hat)
            p.setBrush(QBrush(QColor("white")))
            p.drawRoundedRect(QRectF(66, 44 + b, 86, 14), 7, 7)
            p.drawEllipse(QPointF(164, 14 + b), 8, 8)
        elif acc == "flower":
            cx, cy = 142, 60 + b
            p.setPen(QPen(dark, 1.5))
            p.setBrush(QBrush(QColor("#ffb3d1")))
            for i in range(5):
                ang = math.radians(i * 72 - 90)
                p.drawEllipse(QPointF(cx + 7 * math.cos(ang), cy + 7 * math.sin(ang)), 6, 6)
            p.setBrush(QBrush(QColor("#ffd54f")))
            p.drawEllipse(QPointF(cx, cy), 4.5, 4.5)
        elif acc == "sunhat":
            p.setPen(QPen(dark, 2))
            p.setBrush(QBrush(QColor("#ecd393")))
            p.drawEllipse(QPointF(110, 52 + b), 78, 13)
            p.drawChord(QRectF(80, 20 + b, 60, 50), 0, 180 * 16)
            p.setBrush(QBrush(QColor("#7fb6e8")))
            p.drawRect(QRectF(81, 38 + b, 58, 8))
        elif acc == "beret":
            p.save()
            p.translate(118, 46 + b)
            p.rotate(10)
            p.setPen(QPen(dark, 2))
            p.setBrush(QBrush(QColor("#a23b3f")))
            p.drawEllipse(QPointF(0, 0), 52, 15)
            p.drawLine(QPointF(0, -15), QPointF(1, -21))
            p.restore()
            p.setPen(QPen(dark, 1.5))
            p.setBrush(QBrush(QColor("#e8833a")))
            p.drawEllipse(QPointF(83, 70 + b), 6, 9)
        elif acc == "bunny":
            p.setPen(QPen(dark, 2))
            for cx, tilt in ((92, -10), (128, 14)):
                p.save()
                p.translate(cx, 34 + b)
                p.rotate(tilt)
                p.setBrush(QBrush(QColor("#fbf8ff")))
                p.drawEllipse(QPointF(0, -10), 10, 26)
                p.setBrush(QBrush(QColor("#f27fa8")))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(0, -8), 5, 18)
                p.setPen(QPen(dark, 2))
                p.restore()
        elif acc == "glasses":
            p.setPen(QPen(QColor("#e3b64e"), 2.4))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(91, 104 + b), 10, 10)
            p.drawEllipse(QPointF(129, 104 + b), 10, 10)
            p.drawLine(QPointF(101, 103 + b), QPointF(119, 103 + b))
        elif acc == "bow":
            p.setPen(QPen(dark, 1.8))
            p.setBrush(QBrush(QColor("#f27fa8")))
            cx, cy = 80, 52 + b
            p.drawPolygon(QPolygonF([QPointF(cx, cy), QPointF(cx - 18, cy - 10), QPointF(cx - 18, cy + 9)]))
            p.drawPolygon(QPolygonF([QPointF(cx, cy), QPointF(cx + 18, cy - 10), QPointF(cx + 18, cy + 9)]))
            p.drawEllipse(QPointF(cx, cy), 5, 5)
        elif acc == "star":
            p.setPen(QPen(dark, 1.6))
            p.setBrush(QBrush(QColor("#ffd54f")))
            cx, cy = 147, 78 + b
            pts = []
            for k in range(10):
                a = -math.pi / 2 + k * math.pi / 5
                r = 9 if k % 2 == 0 else 4
                pts.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
            p.drawPolygon(QPolygonF(pts))
        elif acc == "party":
            # little striped cone tilted on the right side of her head, pom-pom on top
            p.save()
            p.translate(132, 34 + b)
            p.rotate(18)
            p.setPen(QPen(dark, 2))
            p.setBrush(QBrush(QColor("#7ec8f0")))
            cone = QPolygonF([QPointF(-17, 14), QPointF(17, 14), QPointF(0, -30)])
            p.drawPolygon(cone)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor("#ffd54f")))
            for y0, hw in ((-12, 7), (2, 12.5)):
                p.drawPolygon(QPolygonF([QPointF(-hw, y0), QPointF(hw, y0),
                                         QPointF(hw + 2, y0 + 5), QPointF(-hw - 2, y0 + 5)]))
            p.setPen(QPen(dark, 2))
            p.setBrush(Qt.NoBrush)
            p.drawPolygon(cone)
            p.setBrush(QBrush(QColor("#f27fa8")))
            p.drawEllipse(QPointF(0, -32), 6, 6)
            p.restore()
        elif acc == "heart":
            # a pink heart hair clip on the right side
            cx, cy = 146, 58 + b
            p.setPen(QPen(dark, 1.8))
            p.setBrush(QBrush(QColor("#f25c8a")))
            heart = QPainterPath()
            heart.moveTo(cx, cy + 9)
            heart.cubicTo(cx - 14, cy, cx - 9, cy - 11, cx, cy - 4)
            heart.cubicTo(cx + 9, cy - 11, cx + 14, cy, cx, cy + 9)
            p.drawPath(heart)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(255, 255, 255, 170)))
            p.drawEllipse(QPointF(cx - 4.5, cy - 3), 2.2, 1.6)
        elif acc == "scarf":
            b += 7
            p.setPen(QPen(dark, 2))
            p.setBrush(QBrush(QColor("#e8636f")))
            p.drawRoundedRect(QRectF(84, 123 + b, 52, 13), 6, 6)
            p.drawRoundedRect(QRectF(118, 129 + b, 13, 28), 5, 5)
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawLine(QPointF(119, 150 + b), QPointF(130, 150 + b))
            p.drawLine(QPointF(119, 144 + b), QPointF(130, 144 + b))

    def draw_vector_pet(self, p, b, happy_eyes):
        # ears and body
        p.setPen(QPen(OUTLINE, 3))
        p.setBrush(QBrush(BODY))
        p.drawPolygon(QPolygonF([QPointF(60, 110 + b), QPointF(70, 70 + b), QPointF(100, 98 + b)]))
        p.drawPolygon(QPolygonF([QPointF(160, 110 + b), QPointF(150, 70 + b), QPointF(120, 98 + b)]))
        p.drawEllipse(QRectF(40, 90 + b, 140, 135))

        # where is the mouse? (eyes follow it)
        cp = self.mapFromGlobal(QCursor.pos())
        dx = cp.x() - 110
        dy = cp.y() - (145 + b)
        dist = math.hypot(dx, dy) or 1.0
        k = min(1.0, dist / 150.0)
        ox = dx / dist * 3.0 * k
        oy = dy / dist * 3.0 * k

        # eyes
        for x in (85, 135):
            y = 145 + b
            if self.surprised:
                p.setPen(QPen(DARK, 2))
                p.setBrush(QBrush(QColor("white")))
                p.drawEllipse(QPointF(x, y), 11, 12)
                p.setBrush(QBrush(DARK))
                p.drawEllipse(QPointF(x, y), 4, 4)
            elif self.sleepy:
                p.setPen(QPen(DARK, 3))
                p.setBrush(Qt.NoBrush)
                p.drawArc(QRectF(x - 10, y - 6, 20, 12), 180 * 16, 180 * 16)
            elif happy_eyes:
                p.setPen(QPen(DARK, 3))
                p.setBrush(Qt.NoBrush)
                p.drawArc(QRectF(x - 10, y - 8, 20, 16), 0, 180 * 16)
            elif self.blink:
                p.setPen(QPen(DARK, 3))
                p.drawLine(x - 9, y, x + 9, y)
            else:
                p.setPen(QPen(DARK, 1))
                p.setBrush(QBrush(DARK))
                p.drawEllipse(QPointF(x + ox, y + oy), 9, 11)
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor("white")))
                p.drawEllipse(QPointF(x + ox - 1.5, y + oy - 4.5), 2.5, 2.5)

        # blush
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(BLUSH))
        for x in (66, 154):
            p.drawEllipse(QRectF(x - 10, 163 + b, 20, 12))

        # mouth
        open_mouth = (self.happy or self.reminder_active or self.jump > 0
                      or (self.singing and (self.t // 6) % 2 == 0))
        if self.surprised:
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(DARK))
            p.drawEllipse(QRectF(104, 161 + b, 12, 14))
        elif self.sleepy:
            p.setPen(QPen(DARK, 3))
            p.setBrush(Qt.NoBrush)
            p.drawLine(104, 167 + b, 116, 167 + b)
        elif open_mouth:
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(DARK))
            p.drawEllipse(QRectF(100, 160 + b, 20, 17))
        else:
            p.setPen(QPen(DARK, 3))
            p.setBrush(Qt.NoBrush)
            p.drawArc(QRectF(98, 155 + b, 24, 20), 200 * 16, 140 * 16)

        # outfit
        acc = self.current_accessory()
        if acc:
            self.draw_accessory(p, b, "hat" if acc == "santa" else acc)

    def paintEvent(self, event):
        # if anything goes wrong while drawing her, the painter still gets closed. (A painter left
        # open blocks every picture after it, and she flashes white over and over.)
        p = QPainter(self)
        try:
            self.paint_pet(p)
        except Exception:
            now = time.time()
            if now - getattr(self, "paint_err_at", 0) > 30:       # don't flood the log
                self.paint_err_at = now
                import traceback
                traceback.print_exc()
        finally:
            if p.isActive():
                p.end()

    def paint_pet(self, p):
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.pad_x or self.pad_y:
            p.translate(self.pad_x, self.pad_y)     # bigger window while she swings

        # hiding behind a window: don't draw her body where the window covers her
        clip = None
        if self.mode == "peek" and self.clip_rect is not None:
            local = self.clip_rect.translated(-self.x(), -self.y())
            clip = QRegion(self.rect()).subtracted(QRegion(local))

        b = int(3 * math.sin(self.t / 6))
        if self.sleepy:
            b = int(2 * math.sin(self.t / 14))
        if self.singing:
            b = int(5 * math.sin(self.t / 3))
        if self.walking:
            amp = 14 if self.mode == "perch" else 10
            b = -int(abs(math.sin(self.t / 4)) * amp)
        if self.reminder_active:
            b = -int(abs(math.sin(self.t / 3)) * 12)
        if self.happy:
            b -= 4
        if self.surprised:
            b -= 8
        if self.jump > 0:
            progress = (20 - self.jump) / 20.0
            b -= int(35 * math.sin(math.pi * progress))

        happy_eyes = (self.happy or self.reminder_active or self.singing
                      or self.petting or self.jump > 0)

        # the 3D frames already bob and sway on their own
        if self.frames:
            b = 0
            if self.reminder_active:
                b = -int(abs(math.sin(self.t / 3)) * 12)
            if self.jump > 0:
                progress = (20 - self.jump) / 20.0
                b -= int(35 * math.sin(math.pi * progress))

        if self.med_end and not self.dragging:
            self.draw_breath_glow(p)
            if self.frames and "meditate" not in self.frames:
                self.draw_zafu(p)
        # her body (dances when music plays)
        p.save()
        if clip is not None and not self.frames:
            p.setClipRegion(clip)
        if self.frames:
            pm, dressed, flip, state = self.frame_for(happy_eyes)
            if self.swing:
                p.translate(110, 50)            # top of her head
                p.rotate(self.swing)
                p.translate(-110, -50)
            if flip:
                p.translate(220, 0)
                p.scale(-1, 1)
            # tall frames have 100px more headroom above her, same size and floor
            extra = (pm.height() - 480) * 0.431
            target = QRectF(15, 38 + b - extra, 190, 207 + extra)
            p.save()
            if clip is not None:
                # the clip is in window coordinates, but the painter may be mirrored
                # (peeking from a window's left side) - undo that so the right part is hidden
                inv, ok = p.worldTransform().inverted()
                p.setClipRegion(inv.map(clip) if ok else clip)
            if time.time() < max(self.shiver_until, self.scared_until):
                p.translate(random.uniform(-2.5, 2.5), 0)        # shaking
            p.setOpacity(self.teleport_alpha())
            self.draw_layers(p, target, pm, getattr(self, "cur_hair", None),
                             getattr(self, "cur_bottom", None))
            p.restore()
            if state.startswith("peek"):
                hands = self.frames.get(state + "_hands")
                if hands:                       # mittens grip the window edge, on top of it
                    hp = hands[(self.t // 6) % len(hands)]
                    hx = (hp.height() - 480) * 0.431
                    p.drawPixmap(QRectF(15, 38 + b - hx, 190, 207 + hx), hp, QRectF(hp.rect()))
            acc = self.current_accessory()
            if (acc and not self.bed and not dressed
                    and not state.startswith("peek") and state in ACC_DROP_OK
                    and not (acc in HAND_ACCS and state.startswith(HAND_BUSY))):
                self.draw_pinned_accessory(p, pm, target, acc)
        elif self.singing and self.dance_enabled:
            p.translate(110, 150)
            p.rotate(7 * math.sin(self.t / 5))
            p.translate(-110, -150)
        if self.frames:
            pass
        elif self.art:
            pm = self.art[self.art_state(happy_eyes)]
            p.drawPixmap(QRectF(0, b, 220, 240), pm, QRectF(pm.rect()))
        else:
            self.draw_vector_pet(p, b, happy_eyes)
        p.restore()

        # zzz while sleeping
        if self.sleepy or self.bed:
            zy = {"futon": 150, "petbed": 120, "dock": 98}.get(self.bed, 115)
            p.setFont(QFont("Helvetica", 13))
            p.setPen(QPen(NOTE))
            for i, ch in enumerate(("z", "Z", "Z")):
                phase = (self.t // 2 + i * 14) % 42
                p.drawText(QPointF(150 + i * 6 + phase * 0.4,
                                   zy + b - phase * 1.4), ch)
        if time.time() < self.pout_until:
            self.draw_pout(p, b)
        if self.frames and self.movie_settled() and not self.bed:
            self.draw_popcorn(p)
        if (self.frames and self.gaming and self.corner_settled() and not self.bed
                and "gaming" not in self.frames):
            self.draw_gamepad(p)                  # (until her 3D gaming frames are in)
        self.draw_fun_effects(p, b)
        if self.bed == "dock":
            self.draw_battery(p)
        elif (self.on_battery and self.batt_pct is not None and self.batt_pct <= BATTERY_LOW
              and not self.bed):
            self.draw_low_battery(p)
        if self.poof > 0:
            self.draw_poof(p)

        # little mic while she's listening
        if self.ears is not None and self.ears.mode is not None:
            p.setFont(QFont("Helvetica", 15))
            p.setPen(QPen(QColor("#e05a8a")))
            p.drawText(QPointF(160, 80), "\U0001F3A4")

        # hearts and music notes
        p.setFont(QFont("Helvetica", 16))
        for x, y, _, ch in self.hearts:
            p.setPen(QPen(HEART if ch == "\u2665" else NOTE))
            p.drawText(QPointF(x, y), ch)

        # timer label
        label = None
        if self.med_end and not self.med_awaiting_more:
            left = max(0, int(self.med_end - time.time()))
            label = f"breathe {left // 60}:{left % 60:02d}"
        elif self.focus_end:
            left = max(0, int(self.focus_end - time.time()))
            name = "pomodoro" if self.pomo else "focus"
            label = f"{name} {left // 60}:{left % 60:02d}"
        elif self.break_end:
            left = max(0, int(self.break_end - time.time()))
            label = f"break {left // 60}:{left % 60:02d}"
        if label:
            p.setPen(QPen(OUTLINE, 2))
            p.setBrush(QBrush(QColor("white")))
            p.drawRoundedRect(QRectF(55, 224, 110, 15), 7, 7)
            p.setPen(QPen(DARK))
            p.setFont(QFont("Helvetica", 9))
            center = QTextOption(Qt.AlignCenter)
            p.drawText(QRectF(55, 224, 110, 15), label, center)

        # (her speech bubble is its own window now: BubbleWin)

        p.end()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("DigiPal")
    if HELPER:
        # her windows don't show in the taskbar, so don't quit when a dialog closes
        app.setQuitOnLastWindowClosed(False)
        # Digi's windows are designed light; in dark mode Windows/Linux would put white text on
        # her white buttons. So her menus and windows always use a light look.
        try:
            app.styleHints().setColorScheme(Qt.ColorScheme.Light)
        except Exception:
            pass
        from PySide6.QtGui import QPalette
        app.setStyle("Fusion")
        pal = QPalette()
        for role, col in ((QPalette.Window, "#f7f5fb"), (QPalette.WindowText, "#2b2540"),
                          (QPalette.Base, "#ffffff"), (QPalette.AlternateBase, "#f1edf9"),
                          (QPalette.Text, "#2b2540"), (QPalette.Button, "#ffffff"),
                          (QPalette.ButtonText, "#3a3159"), (QPalette.ToolTipBase, "#ffffff"),
                          (QPalette.ToolTipText, "#2b2540"), (QPalette.Highlight, "#a99be0"),
                          (QPalette.HighlightedText, "#ffffff"), (QPalette.PlaceholderText, "#9a93b0")):
            pal.setColor(role, QColor(col))
        app.setPalette(pal)
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DigiPal.Digi")
        except Exception:
            pass
    _icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
    if os.path.exists(_icon):
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(_icon))
    # only one Digi at a time: if she's already running, this copy just quietly leaves
    from PySide6.QtCore import QLockFile, QDir
    _lock = QLockFile(os.path.join(QDir.tempPath(), "digipal.lock"))
    _lock.setStaleLockTime(0)
    if not _lock.tryLock(3000):
        sys.exit(0)
    APP_LOCK = _lock
    pet = Pet()
    pet.show()
    sys.exit(app.exec())
