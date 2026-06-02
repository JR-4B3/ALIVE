# codebook.py
# Dual-tone frequency codebook (DTMF-inspired).
# Each letter = one LOW frequency + one HIGH frequency played simultaneously.
# Receiver extracts the two peaks via FFT.
# Gaps between bursts are a secondary timing channel + ALIVE/DEAD classifier.

LOW_FREQS  = [400, 500, 600, 700, 800, 900, 1000]
HIGH_FREQS = [2000, 2300, 2600, 2900]

# 7 x 4 = 28 combos (27 used for A-Z + space)
FREQ_MAP = {
    'A': (400, 2000),  'B': (400, 2300),  'C': (400, 2600),  'D': (400, 2900),
    'E': (500, 2000),  'F': (500, 2300),  'G': (500, 2600),  'H': (500, 2900),
    'I': (600, 2000),  'J': (600, 2300),  'K': (600, 2600),  'L': (600, 2900),
    'M': (700, 2000),  'N': (700, 2300),  'O': (700, 2600),  'P': (700, 2900),
    'Q': (800, 2000),  'R': (800, 2300),  'S': (800, 2600),  'T': (800, 2900),
    'U': (900, 2000),  'V': (900, 2300),  'W': (900, 2600),  'X': (900, 2900),
    'Y': (1000, 2000), 'Z': (1000, 2300), ' ': (1000, 2600),
    # (1000, 2900) is unused / reserved
}

REV_FREQ = {v: k for k, v in FREQ_MAP.items()}

GAP_MAP = {
    'A': 100, 'B': 150, 'C': 200, 'D': 250, 'E': 300,
    'F': 350, 'G': 400, 'H': 450, 'I': 500, 'J': 550,
    'K': 600, 'L': 650, 'M': 700, 'N': 750, 'O': 800,
    'P': 850, 'Q': 900, 'R': 950, 'S': 1000, 'T': 1050,
    'U': 1100, 'V': 1150, 'W': 1200, 'X': 1250, 'Y': 1300,
    'Z': 1350, ' ': 1600,
}

REV_GAP = {v: k for k, v in GAP_MAP.items()}


# embedded word list for gibberish detection
COMMON_WORDS = {
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "ANY", "HAD", "HER", "WAS",
    "ONE", "OUR", "DAY", "USE", "MAN", "NEW", "NOW", "WAY", "MAY", "SAY", "SHE", "TRY",
    "ASK", "END", "WHY", "LET", "PUT", "TOO", "OLD", "TELL", "VERY", "WHEN", "YOUR",
    "ALSO", "BACK", "CALL", "COME", "COULD", "EVEN", "FIND", "FIRST", "GIVE", "GOOD",
    "HERE", "HOME", "JUST", "KNOW", "LAST", "LEFT", "LIFE", "LIVE", "LOOK", "MADE", "MAKE",
    "MOST", "MOVE", "MUCH", "MUST", "NAME", "NEED", "NEXT", "ONLY", "OPEN", "OVER", "PART",
    "PLAY", "RIGHT", "SAID", "SAME", "SEEM", "SHOW", "SIDE", "TAKE", "THAN", "THEM", "TIME",
    "TURN", "WANT", "WELL", "WENT", "WERE", "WHAT", "WITH", "WORD", "WORK", "YEAR", "HELLO",
    "WORLD", "TEST", "DEMO", "ALIVE", "DEAD", "SIGNAL", "HI", "A", "I", "OK", "YES", "NO",
    "GO", "UP", "ON", "OFF", "OUT", "BY", "ME", "MY", "WE", "US", "DO", "DID", "CAN",
    "HAS", "HIS", "HOW", "ITS", "OIL", "SIT", "SET", "RUN", "SUN", "SON", "EAT", "ATE",
    "SEA", "SEE", "EACH", "EASY", "IDEA", "AREA", "AGREE", "ABOUT", "AFTER", "AGAIN",
    "ALONG", "ALREADY", "ALWAYS", "AMONG", "ANOTHER", "AROUND", "BECAUSE", "BEFORE",
    "BELOW", "BETWEEN", "BOTH", "CHANGE", "CHILD", "CITY", "CLOSE", "COLD", "COLOR",
    "COMPANY", "COMPLETE", "CONTROL", "CORRECT", "COURSE", "CREATE", "CURRENT", "DECIDE",
    "DEVELOP", "DIFFERENT", "DIRECT", "DISCOVER", "DOOR", "DURING", "EARLY", "EARTH",
    "EFFECT", "EFFORT", "ENOUGH", "ENTIRE", "ESPECIALLY", "EVERY", "EVERYTHING",
    "EXAMPLE", "EXPERIENCE", "EYE", "FACE", "FACT", "FAMILY", "FATHER", "FEEL", "FEW",
    "FIELD", "FINAL", "FINALLY", "FISH", "FLOOR", "FOLLOW", "FOOD", "FOOT", "FORCE",
    "FORM", "FREE", "FRIEND", "FRONT", "FULL", "FUTURE", "GAME", "GARDEN", "GENERAL",
    "GIRL", "GLAD", "GREAT", "GROUP", "GROW", "GUESS", "HAPPEN", "HAPPY", "HARD",
    "HAVE", "HEAD", "HEAR", "HEART", "HEAT", "HEAVY", "HELP", "HISTORY", "HOLD",
    "HOLE", "HOPE", "HORSE", "HOUR", "HOUSE", "HUNDRED", "HURRY", "HURT", "ICE",
    "INCLUDE", "INCREASE", "INDEED", "INDICATE", "INDUSTRY", "INFORMATION", "INSIDE",
    "INSTEAD", "INTEREST", "INTO", "INTRODUCE", "INVEST", "INVITE", "INVOLVE",
    "ISLAND", "ISSUE", "ITEM", "ITSELF", "JOB", "JOIN", "JUMP", "KEEP", "KEY",
    "KILL", "KIND", "KING", "KITCHEN", "KNOWLEDGE", "LAND", "LANGUAGE", "LARGE",
    "LATE", "LAUGH", "LAW", "LEAD", "LEARN", "LEAST", "LEAVE", "LENGTH", "LESS",
    "LEVEL", "LIGHT", "LIKE", "LINE", "LIST", "LISTEN", "LITTLE", "LOCAL", "LONG",
    "LOSE", "LOSS", "LOVE", "LOW", "MAIN", "MAJOR", "MALE", "MANY", "MARKET", "MASS",
    "MATCH", "MATERIAL", "MATTER", "MEAN", "MEASURE", "MEDIA", "MEDICAL", "MEET",
    "MEMBER", "MENTION", "MESSAGE", "METAL", "METHOD", "MIDDLE", "MIGHT", "MILE",
    "MILITARY", "MILLION", "MIND", "MINUTE", "MISS", "MISSION", "MODEL", "MODERN",
    "MOMENT", "MONEY", "MONTH", "MORE", "MORNING", "MOTHER", "MOTION", "MOVIE",
    "MUSIC", "MYSELF", "NAME", "NATION", "NATIONAL", "NATURAL", "NATURE", "NEAR",
    "NEARLY", "NECESSARY", "NETWORK", "NEVER", "NEWS", "NEWSPAPER", "NICE", "NIGHT",
    "NONE", "NORTH", "NOTE", "NOTICE", "NOTION", "NUMBER", "OBJECT", "OBTAIN",
    "OBVIOUS", "OCCASION", "OCCUR", "OFFER", "OFFICE", "OFFICER", "OFFICIAL", "OFTEN",
    "ONCE", "OPERATE", "OPERATION", "OPINION", "OPPORTUNITY", "OPPOSITE", "OPTION",
    "ORDER", "ORGANIZATION", "ORIGIN", "ORIGINAL", "OTHER", "OUTCOME", "OUTSIDE",
    "OWN", "OWNER", "PAGE", "PAIN", "PAINT", "PAPER", "PARENT", "PARK", "PART",
    "PARTICULAR", "PARTY", "PASS", "PAST", "PATIENT", "PATTERN", "PAY", "PEACE",
    "PEOPLE", "PERCENT", "PERFECT", "PERFORM", "PERFORMANCE", "PERHAPS", "PERIOD",
    "PERMANENT", "PERSON", "PERSONAL", "PHYSICAL", "PICK", "PICTURE", "PIECE", "PLACE",
    "PLAN", "PLANE", "PLANT", "PLAYER", "PLEASE", "POINT", "POLICE", "POLICY",
    "POLITICAL", "POOL", "POOR", "POPULAR", "POPULATION", "POSITION", "POSITIVE",
    "POSSIBLE", "POST", "POTENTIAL", "POUND", "POWER", "PRACTICE", "PREFER", "PRESENT",
    "PRESIDENT", "PRESS", "PRESSURE", "PRETTY", "PREVENT", "PREVIOUS", "PRICE",
    "PRIMARY", "PRIME", "PRINCIPLE", "PRIORITY", "PRIVATE", "PRIZE", "PROBABLY",
    "PROBLEM", "PROCESS", "PRODUCE", "PRODUCT", "PRODUCTION", "PROFESSIONAL",
    "PROFESSOR", "PROGRAM", "PROGRESS", "PROJECT", "PROMISE", "PROMOTE", "PROPER",
    "PROPOSE", "PROTECT", "PROTECTION", "PROVE", "PROVIDE", "PUBLIC", "PULL",
    "PURPOSE", "PUSH", "QUALITY", "QUARTER", "QUESTION", "QUICK", "QUICKLY", "QUIET",
    "QUITE", "RACE", "RADIO", "RAISE", "RANGE", "RATE", "RATHER", "REACH", "READ",
    "READY", "REAL", "REALITY", "REALIZE", "REALLY", "REASON", "RECEIVE", "RECENT",
    "RECENTLY", "RECOGNIZE", "RECORD", "RED", "REDUCE", "REFLECT", "REGION", "RELATE",
    "RELATION", "RELATIONSHIP", "RELATIVE", "RELATIVELY", "RELEASE", "REMAIN",
    "REMEMBER", "REMOVE", "REPEAT", "REPLACE", "REPLY", "REPORT", "REPRESENT",
    "REPRESENTATIVE", "REQUIRE", "RESEARCH", "RESOURCE", "RESPECT", "RESPOND",
    "RESPONSE", "RESPONSIBILITY", "RESPONSIBLE", "REST", "RESTAURANT", "RESULT",
    "RETAIN", "RETURN", "REVEAL", "REVENUE", "REVIEW", "RICH", "RIDE", "RING",
    "RISE", "RISK", "RIVER", "ROAD", "ROCK", "ROLE", "ROLL", "ROOM", "RULE", "RUN",
    "SAFE", "SAVE", "SCENE", "SCHOOL", "SCIENCE", "SCIENTIFIC", "SCIENTIST", "SCORE",
    "SCREEN", "SEA", "SEARCH", "SEASON", "SEAT", "SECOND", "SECRET", "SECTION",
    "SECURITY", "SEE", "SEEK", "SEEM", "SEEN", "SELECT", "SELECTION", "SELF",
    "SELL", "SEND", "SENIOR", "SENSE", "SENSITIVE", "SENTENCE", "SEPARATE", "SERIES",
    "SERIOUS", "SERVE", "SERVICE", "SET", "SETTLE", "SEVERAL", "SEVERE", "SEX",
    "SEXUAL", "SHAKE", "SHALL", "SHAPE", "SHARE", "SHARP", "SHE", "SHEET", "SHELL",
    "SHIFT", "SHIP", "SHIRT", "SHOCK", "SHOE", "SHOOT", "SHOP", "SHORT", "SHOULDER",
    "SHOW", "SIDE", "SIGN", "SIGNIFICANCE", "SIGNIFICANT", "SILENCE", "SIMILAR",
    "SIMILARLY", "SIMPLE", "SIMPLY", "SINCE", "SING", "SINGLE", "SIR", "SISTER",
    "SIT", "SITE", "SITUATION", "SIZE", "SKILL", "SKIN", "SKY", "SLEEP", "SLICE",
    "SLIDE", "SLIGHT", "SLIGHTLY", "SLIP", "SLOW", "SLOWLY", "SMALL", "SMART",
    "SMELL", "SMILE", "SMOKE", "SMOOTH", "SNAP", "SNOW", "SO", "SOCIAL", "SOCIETY",
    "SOFT", "SOFTWARE", "SOIL", "SOLAR", "SOLDIER", "SOLID", "SOLUTION", "SOLVE",
    "SOMEBODY", "SOMEHOW", "SOMEONE", "SOMETHING", "SOMETIME", "SOMETIMES", "SOMEWHAT",
    "SOMEWHERE", "SON", "SONG", "SOON", "SORT", "SOUND", "SOURCE", "SOUTH", "SOUTHERN",
    "SPACE", "SPEAK", "SPEAKER", "SPECIAL", "SPECIES", "SPECIFIC", "SPEECH", "SPEED",
    "SPEND", "SPENDING", "SPIN", "SPIRIT", "SPORT", "SPOT", "SPREAD", "SPRING",
    "SQUARE", "SQUEEZE", "STABILITY", "STABLE", "STAFF", "STAGE", "STAIR", "STAKE",
    "STAND", "STANDARD", "STAR", "STARE", "START", "STATE", "STATEMENT", "STATION",
    "STATISTICS", "STATUS", "STAY", "STEADY", "STEAL", "STEP", "STICK", "STILL",
    "STIR", "STOCK", "STOMACH", "STONE", "STOP", "STORAGE", "STORE", "STORM",
    "STORY", "STRAIGHT", "STRANGE", "STRANGER", "STRATEGIC", "STRATEGY", "STREAM",
    "STREET", "STRENGTH", "STRETCH", "STRIKE", "STRING", "STRIP", "STRONG", "STRONGLY",
    "STRUCTURE", "STRUGGLE", "STUDENT", "STUDIO", "STUDY", "STUFF", "STUPID", "STYLE",
    "SUBJECT", "SUBMIT", "SUBSEQUENT", "SUBSTANCE", "SUBSTANTIAL", "SUCCEED", "SUCCESS",
    "SUCCESSFUL", "SUCCESSFULLY", "SUCH", "SUDDEN", "SUDDENLY", "SUE", "SUFFER",
    "SUFFICIENT", "SUGAR", "SUGGEST", "SUGGESTION", "SUICIDE", "SUIT", "SUMMER",
    "SUMMIT", "SUN", "SUPER", "SUPPLY", "SUPPORT", "SUPPORTER", "SUPPOSE", "SUPPOSED",
    "SUPREME", "SURE", "SURELY", "SURFACE", "SURGERY", "SURPRISE", "SURPRISED",
    "SURROUND", "SURVEY", "SURVIVAL", "SURVIVE", "SURVIVOR", "SUSPECT", "SUSTAIN",
    "SWEAR", "SWEAT", "SWEEP", "SWEET", "SWIM", "SWING", "SWITCH", "SYMBOL",
    "SYMPATHY", "SYSTEM", "TABLE", "TACKLE", "TACTIC", "TAIL", "TAKE", "TALE",
    "TALENT", "TALK", "TALL", "TANK", "TAP", "TAPE", "TARGET", "TASK", "TASTE",
    "TAX", "TAXPAYER", "TEA", "TEACH", "TEACHER", "TEACHING", "TEAM", "TEAR",
    "TELEPHONE", "TELEVISION", "TELL", "TEMPERATURE", "TEMPORARY", "TEN", "TEND",
    "TENDENCY", "TENNIS", "TENSION", "TENT", "TERM", "TERMS", "TERRIBLE", "TERRITORY",
    "TERROR", "TERRORISM", "TERRORIST", "TEST", "TESTIFY", "TESTIMONY", "TESTING",
    "TEXT", "THANK", "THANKS", "THAT", "THEATER", "THEIR", "THEM", "THEME",
    "THEMSELVES", "THEN", "THEORY", "THERAPY", "THERE", "THEREFORE", "THESE", "THEY",
    "THICK", "THIN", "THING", "THINK", "THINKING", "THIRD", "THIRTY", "THIS", "THOSE",
    "THOUGH", "THOUGHT", "THOUSAND", "THREAT", "THREATEN", "THREE", "THROAT", "THROUGH",
    "THROUGHOUT", "THROW", "THUS", "TICKET", "TIE", "TIGHT", "TIME", "TINY", "TIP",
    "TIRE", "TIRED", "TISSUE", "TITLE", "TO", "TOBACCO", "TODAY", "TOE", "TOGETHER",
    "TOMATO", "TOMORROW", "TONE", "TONGUE", "TONIGHT", "TOOL", "TOOTH", "TOP",
    "TOPIC", "TOSS", "TOTAL", "TOTALLY", "TOUCH", "TOUGH", "TOUR", "TOURIST",
    "TOURNAMENT", "TOWARD", "TOWARDS", "TOWER", "TOWN", "TOY", "TRACE", "TRACK",
    "TRADE", "TRADITION", "TRADITIONAL", "TRAFFIC", "TRAGEDY", "TRAIL", "TRAIN",
    "TRAINING", "TRANSFER", "TRANSFORM", "TRANSFORMATION", "TRANSITION", "TRANSLATE",
    "TRANSPORTATION", "TRAVEL", "TREAT", "TREATMENT", "TREATY", "TREE", "TREMENDOUS",
    "TREND", "TRIAL", "TRIBE", "TRICK", "TRIP", "TROOP", "TROUBLE", "TRUCK", "TRUE",
    "TRULY", "TRUST", "TRUTH", "TRY", "TUBE", "TUNNEL", "TURN", "TV", "TWELVE",
    "TWENTY", "TWICE", "TWIN", "TWO", "TYPE", "TYPICAL", "TYPICALLY", "UGLY",
    "ULTIMATE", "ULTIMATELY", "UNABLE", "UNCLE", "UNDER", "UNDERGO", "UNDERSTAND",
    "UNDERSTANDING", "UNFORTUNATELY", "UNHAPPY", "UNION", "UNIQUE", "UNIT", "UNITED",
    "UNIVERSAL", "UNIVERSE", "UNIVERSITY", "UNKNOWN", "UNLESS", "UNLIKE", "UNLIKELY",
    "UNTIL", "UNUSUAL", "UP", "UPON", "UPPER", "UPSET", "URBAN", "URGE", "US", "USE",
    "USED", "USEFUL", "USER", "USUAL", "USUALLY", "UTILITY", "VACATION", "VALLEY",
    "VALUABLE", "VALUE", "VARIABLE", "VARIATION", "VARIETY", "VARIOUS", "VARY",
    "VAST", "VEGETABLE", "VEHICLE", "VENTURE", "VERSION", "VERSUS", "VERY", "VESSEL",
    "VETERAN", "VIA", "VICTIM", "VICTORY", "VIDEO", "VIEW", "VIEWER", "VILLAGE",
    "VIOLATE", "VIOLATION", "VIOLENCE", "VIOLENT", "VIRTUALLY", "VIRTUE", "VIRUS",
    "VISIBLE", "VISION", "VISIT", "VISITOR", "VISUAL", "VITAL", "VOICE", "VOLUME",
    "VOLUNTEER", "VOTE", "VOTER", "VS", "VULNERABLE", "WAGE", "WAIT", "WAKE", "WALK",
    "WALL", "WANDER", "WANT", "WAR", "WARM", "WARN", "WARNING", "WASH", "WASTE",
    "WATCH", "WATER", "WAVE", "WE", "WEAK", "WEALTH", "WEAR", "WEATHER", "WEDDING",
    "WEEK", "WEEKEND", "WEEKLY", "WEIGH", "WEIGHT", "WELCOME", "WELFARE", "WELL",
    "WEST", "WESTERN", "WET", "WHAT", "WHATEVER", "WHEEL", "WHEN", "WHENEVER",
    "WHERE", "WHEREAS", "WHETHER", "WHICH", "WHILE", "WHISPER", "WHITE", "WHO",
    "WHOLE", "WHOM", "WHOSE", "WHY", "WIDE", "WIDELY", "WIDESPREAD", "WIFE",
    "WILD", "WILL", "WILLING", "WIN", "WIND", "WINDOW", "WINE", "WING", "WINNER",
    "WINTER", "WIPE", "WIRE", "WISDOM", "WISE", "WISH", "WITH", "WITHDRAW", "WITHIN",
    "WITHOUT", "WITNESS", "WOMAN", "WONDER", "WONDERFUL", "WOOD", "WOODEN", "WORK",
    "WORKER", "WORKING", "WORKS", "WORKSHOP", "WORRIED", "WORRY", "WORTH", "WOULD",
    "WOUND", "WRAP", "WRITE", "WRITER", "WRITING", "WRONG", "YARD", "YEAH", "YEAR",
    "YELL", "YELLOW", "YES", "YESTERDAY", "YET", "YIELD", "YOU", "YOUNG", "YOUR",
    "YOURS", "YOURSELF", "YOUTH", "ZONE",
}


# common English bigrams. real language uses these often; gibberish rarely does.
COMMON_BIGRAMS = {
    "TH", "HE", "IN", "ER", "AN", "RE", "ON", "AT", "EN", "ND",
    "TI", "ES", "OR", "TE", "OF", "ED", "IS", "IT", "AL", "AR",
    "ST", "TO", "NT", "NG", "SE", "HA", "AS", "OU", "IO", "LE",
    "VE", "CO", "ME", "DE", "HI", "RI", "RO", "IC", "NE", "EA",
    "RA", "CE", "LI", "CH", "LL", "BE", "MA", "SI", "OM", "UR",
    "CA", "EL", "TA", "ET", "NO", "LA", "OT", "SS", "AM", "UM",
    "NA", "KE", "OW", "WE", "UL", "HO", "PE", "EE", "GH", "IE",
    "IL", "IM", "DI", "IG", "PH", "FO", "FI", "MI", "GI", "AU",
    "AC", "AP", "AY", "WH", "OL", "YO", "EM", "TS", "CI", "UP",
    "PO", "PA", "EC", "UN", "LO", "BO", "PI", "EV", "ID", "IR",
    "SC", "TU", "OO", "SH", "RC", "FE", "IP", "PR", "AI", "FR",
    "TT", "OW", "WO", "FF", "RR", "CC", "NN", "DD", "GG", "BB",
}


def is_plausible_text(text):
    """Heuristic language check: dictionary, bigram frequency, vowel ratio,
    consonant clusters, word length."""
    text_upper = text.upper().strip().replace(" ", "")
    if len(text_upper) == 0:
        return False

    # very short strings are too ambiguous
    if len(text_upper) <= 2:
        return True

    # dictionary substring check (only words length >= 3)
    for word in COMMON_WORDS:
        if len(word) >= 3 and word in text_upper:
            return True

    # no natural language has words longer than ~12 letters without spaces
    for token in text_upper.split():
        if len(token) > 12:
            return False

    # bigram frequency check
    if len(text_upper) >= 6:
        bigrams = [text_upper[i:i+2] for i in range(len(text_upper) - 1)]
        if bigrams:
            common_count = sum(1 for b in bigrams if b in COMMON_BIGRAMS)
            if common_count / len(bigrams) < 0.18:
                return False

    # vowel ratio sanity check
    vowels = set("AEIOU")
    vowel_count = sum(1 for c in text_upper if c in vowels)
    ratio = vowel_count / len(text_upper)
    if ratio < 0.15 or ratio > 0.60:
        return False

    # impossible consonant cluster check (5+ consonants in a row)
    consonants = 0
    for c in text_upper:
        if c not in vowels:
            consonants += 1
            if consonants >= 5:
                return False
        else:
            consonants = 0

    return True
