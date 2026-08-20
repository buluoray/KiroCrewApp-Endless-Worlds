---
# 《Age of Sword and Flame》V1.0 — machine-readable header.
#
# Every declaration below is traceable to a chapter of the prose that follows.
# The prose itself is never parsed: it is the narrator's instruction set and is
# passed through verbatim. This header exists only so the app knows what to
# render and what to enforce.

id: age-of-sword-and-flame
title: Age of Sword and Flame
version: "1.0"
language: en

# The shelf's emotional entrance: invite the player to imagine a life before
# showing them the machinery behind it.
card:
  promise: Rise from obscurity to the edge of a throne—or live an ordinary life well, close to home.
  possibilities:
    - See a choice from your youth return decades later
    - Decide what you will pay for magic, war, or a quiet life
    - Leave unfinished dreams, secrets, and enemies to the next generation

# Chapter 147 · The Player Status Bar — 【Time】Year XXX · Month XXX
clock:
  unit: month
  label: "Year {year} · Month {month}"

# Chapter 128 · Multi-generation mode / Chapter 161 — grandfather → father →
# player → children → grandchildren, forming a family history spanning centuries.
lineage: true

# Chapter 174 · The formal launch screen — 【Simulation Style】
# Declared here rather than as an opening group: the app renders the style
# chooser from this list, so it is the template's 14th opening question without
# being defined twice.
styles:
  - { id: extreme-real, label: Extreme Realism }
  - { id: classic, label: Classic Western-Fantasy Adventure, default: true }
  - { id: epic, label: Epic Fantasy }
  - { id: dark, label: Dark Fantasy }
  - { id: daily, label: Everyday Life }
  - { id: mixed, label: Mixed Mode }

# Chapter 174 · The formal launch screen — the remaining 13 groups, in the prose's order.
# `custom: true` renders the chapter's free-text tail option.
opening:
  - id: era
    label: Era
    kind: pick
    custom: true
    options: [Age of the Golden Kingdoms, Age of Magical Flourishing, Age of Warring Lords, Eve of the Great Calamity, Age of the Demon Invasion, Age of Postwar Rebuilding]
  - id: race
    label: Race
    kind: pick
    custom: true
    options: [Human, Elf, Dwarf, Halfling, Orc, Dragonborn, Goblin, Fae, Demonkin]
  - id: birth
    label: Birth Station
    kind: pick
    custom: true
    options: [Farmer, Artisan, Merchant, Commoner, Apprentice, Adventurer Family, Knight Family, Noble, Church Family, Academy Family, Royalty]
  - { id: name, label: Name, kind: text }
  # Chapter 161 — begins at age 18, lives to 90.
  - { id: age, label: Age, kind: number }
  - { id: sex, label: Sex, kind: pick, custom: true, options: [Male, Female] }
  - { id: birthplace, label: Birthplace, kind: text }
  - { id: family, label: Family Circumstances, kind: text }
  - { id: skills, label: Starting Skills, kind: text }
  # Chapter 33 · Magical aptitude — "random" becomes the group's Surprise-me
  # action, not an option the player can end up literally holding.
  - id: aptitude
    label: Magical Aptitude
    kind: pick
    random: true
    options: [No Magical Talent, Ordinary, Good, Excellent, Exceptional]
  - { id: faith, label: Starting Faith, kind: text }
  - { id: personality, label: Personality Keywords, kind: text }
  - { id: goal, label: Starting Life Goal, kind: text }

# Chapter 146 · Monthly world evolution — nine categories plus reachable rumour.
# R6.3 gates each by what the character could plausibly know.
digest:
  categories: [Nations, War, Church, Academies, Economy, Magical Beasts, Demonkin, Adventurers, Your Region]
  rumours: true

panels:
  # Chapter 147 · The Player Status Bar — the 17 always-visible fields.
  - id: status
    label: Character Status
    region: status
    always: true
    fields:
      - { id: time, label: Time, primitive: field }
      - { id: age, label: Age, primitive: field }
      - { id: race, label: Race, primitive: field }
      - { id: station, label: Station, primitive: field }
      - { id: location, label: Location, primitive: field }
      - { id: occupation, label: Occupation, primitive: field }
      # Chapter 24 · Currency / Chapter 154 — a domain is not an upgrade menu:
      # a resource shows its short-term effect and its accumulating cost.
      - { id: wealth, label: Wealth, primitive: resource, delayed: true }
      - { id: family, label: Family, primitive: field }
      # Chapter 146 · Social class — a ladder, not a bare number.
      - id: standing
        label: Social Standing
        primitive: rank
        tiers: [Slave, Pauper, Commoner, Freeman, Gentry, Knight, Noble, Great Noble, Royalty]
      # Chapter 39 · Magic rank
      - id: magic
        label: Magic
        primitive: rank
        tiers: [None, Novice, Apprentice, Adept, Expert, Archmage, Sage, Legendary]
      - id: combat
        label: Combat
        primitive: rank
        tiers: [Helpless, Militia, Soldier, Veteran, Knight, Elite, Master, Legendary]
      # Chapter 47 · Divine magic / Chapter 46 · Faith
      - id: faith
        label: Divine Magic / Faith
        primitive: rank
        tiers: [Faithless, Believer, Devout, Deacon, Priest, Bishop, Saint]
      - { id: skills, label: Skills, primitive: inventory }
      # Chapter 29 · Adventurer reputation
      - { id: renown, label: Renown, primitive: stat, min: 0, max: 100 }
      - { id: ties, label: Key Relationships, primitive: people }
      - { id: factions, label: Factions, primitive: field }
      # Chapter 121 · The player's life goal — an open commitment, tracked for staleness.
      - { id: goal, label: Current Goal, primitive: threads }

  # Chapter 148 · Magic panel — "shown additionally when the player has magic".
  # Chapter 122 says a player may never learn magic at all, so this panel
  # must be genuinely absent rather than shown empty.
  - id: magic
    label: Magic
    region: status
    when: state.magic.awakened == true
    fields:
      - { id: mana, label: Mana, primitive: stat }
      - { id: capacity, label: Mana Capacity, primitive: stat }
      - { id: precision, label: Control Precision, primitive: stat }
      - { id: affinity, label: Magical Affinity, primitive: field }
      # Chapter 41 · Schools of magic
      - { id: school, label: Primary School, primitive: field }
      - { id: spells, label: Known Spells, primitive: inventory }
      # Chapter 37 · Inventing magic
      - { id: experiments, label: Magic in Experiment, primitive: threads }
      - { id: research, label: Magical Research, primitive: threads }

  # Chapter 149 · Social relations panel — one roster carrying all eight
  # attributes. Chapter 99 · NPC autonomy means these move whether or not the
  # player is looking.
  - id: relations
    label: Relationships
    region: world
    when: state.relations.known == true
    fields:
      - id: figures
        label: Key Figures
        primitive: people
        attributes: [Name, Station, Race, Relationship, Trust, Interest, Hostility, Recent Activity]

  # Chapter 150 · Nation panel — "if the player becomes high-ranking".
  - id: nation
    label: Nation
    region: world
    when: state.office.high == true
    fields:
      - { id: population, label: Population, primitive: resource, delayed: true }
      - { id: grain, label: Grain, primitive: resource, delayed: true }
      - { id: treasury, label: Treasury, primitive: resource, delayed: true }
      - { id: army, label: Army, primitive: resource, delayed: true }
      - { id: magic-industry, label: Magic Industry, primitive: stat }
      - { id: trade, label: Trade, primitive: stat }
      # Chapter 154 — raise taxes → treasury up → commoner discontent → population
      # flight → revolt.
      - { id: stability, label: Stability, primitive: stat, trend: true }
      - { id: religion, label: Religion, primitive: field }
      - { id: nobility, label: Nobility, primitive: people }
      - { id: cities, label: Cities, primitive: inventory }
      - { id: diplomacy, label: Diplomacy, primitive: people }
      - { id: wars, label: Wars, primitive: threads }

  # Chapter 151 · Academy panel — "if the player joins an academy".
  - id: academy
    label: Academy
    region: world
    when: state.academy.enrolled == true
    fields:
      - { id: standing, label: Academy Standing, primitive: stat }
      - { id: mentor, label: Mentor, primitive: people }
      - { id: school, label: School, primitive: field }
      - { id: research, label: Research, primitive: threads }
      - { id: students, label: Students, primitive: inventory }
      - { id: resources, label: Resources, primitive: resource }
      # Chapter 42 · Rivalry between schools
      - { id: rivals, label: Rival Factions, primitive: people }
      - { id: output, label: Research Output, primitive: inventory }
      - { id: politics, label: Political Ties, primitive: people }

  # Chapter 152 · Family panel — "if the player holds a family".
  # Chapter 129 · Family history accumulates across generations.
  - id: family
    label: Family
    region: world
    when: state.family.held == true
    fields:
      - id: title
        label: Title
        primitive: rank
        tiers: [None, Knight, Baron, Viscount, Count, Marquess, Duke, Grand Duke]
      - { id: domain, label: Domain, primitive: resource, delayed: true }
      - { id: wealth, label: Wealth, primitive: resource, delayed: true }
      - { id: members, label: Members, primitive: people }
      # Chapter 16 · Noble marriage alliances
      - { id: marriages, label: Marriages, primitive: inventory }
      - { id: allies, label: Allies, primitive: people }
      - { id: enemies, label: Enemies, primitive: people }
      - { id: renown, label: Renown, primitive: stat }
      # Chapter 103 · NPC secrets / Chapter 129 — descendants may find secrets
      # ancestors left behind.
      - { id: secrets, label: Family Secrets, primitive: threads }
      # Chapter 127 · Inheritance
      - { id: heirs, label: Heirs, primitive: people }

# Chapter 159 · Doom is not the only ending / Chapter 160 · The final world
# ending — both say the outcome is produced by world state and that there is no
# fixed ending. So this header does NOT enumerate outcome names: it only detects
# that a terminal state was reached, and the narrator writes what it was called.
# Enumerating them here would turn an open world into a menu.
#
# State contract for these conditions, since the `when` interpreter compares
# scalars only and cannot measure a list: the narrator maintains
# `state.alive` (bool), `state.lineage.hasHeir` (bool),
# `state.world.epochClosed` (bool) and `state.retiredByPlayer` (bool).
endings:
  # Chapter 162 — death: real by default. A death with an heir advances the
  # generation (R11) instead of ending the run, so the ending needs both facts.
  - { id: line-ended, when: state.alive == false and not state.lineage.hasHeir }
  - { id: world-epoch-closed, when: state.world.epochClosed == true }
  # R12.5 — the player may end a life early.
  - { id: retired, when: state.retiredByPlayer == true }

# Chapter 170 · The save system — the 16 categories the save must carry.
save:
  - Character
  - Age
  - Race
  - Magic
  - Skills
  - Wealth
  - Family
  - NPCs
  - Factions
  - Nations
  - Map
  - History
  - Wars
  - World Variables
  - Major Events
  - Unfinished Events

# Lore entries — keyword-triggered world background. Also the source of the world
# detail page's structured "World setting" view. Handed to the narrator at the
# opening by handToAgent (turn 1 has no prior prose for keywords to match against).
lore:
  - id: world-structure-history
    name: World Layers and History
    category: World
    summary: The world spans five layers and has passed through millennia of eras; its history is still a living force today.
    keys: [World Structure, History, Eras, Layers]
    text: |
      The world is divided into five layers—the mundane, the civilized, the extraordinary, the otherworlds, and the planes—running from villages, towns, and trade roads, to mage towers, temples, and dungeons, and on to elven realms, dwarven kingdoms, dragon lairs, and the Abyss, all the way to the Material Plane, the divine realms, the Void, and the Dream World. This is a civilized world with thousands of years of history, having passed through eras such as the descent of the gods, the ancient racial civilizations, the flourishing of magic, the founding of the kingdoms, the First Great Calamity, and the human empires. The borders, hatreds, ruins, houses, and religions left behind by ancient wars all persist to this day.
  - id: nine-civilization-pillars
    name: The Nine Pillars of Civilization
    category: World
    summary: Academies, church, guilds, nobles, commoners, slavery, demihumans, magical beasts, and demonkin—nine structures uphold civilization.
    keys: [Pillars of Civilization, Social Institutions, Powers]
    text: |
      The world's civilization rests on nine pillars: the academy system that imparts knowledge; the church system that governs faith, divine magic, and judgment; the guild system that regulates professions and commerce; the noble system that holds land and bloodline; commoner society, engaged in farming, crafts, and city life; the institution of slavery found in some regions; the demihuman civilizations of elves, dwarves, orcs, halflings, and others; the magical beast ecology of the wild; and the demonkin powers from other worlds or the Abyss. Slavery is a social institution rather than a racial label, and demonkin are not all mindless monsters—each power has political aims of its own.
  - id: races-and-culture
    name: Races and Cultures
    category: Race
    summary: Several sapient races each have their own gifts and complete cultures, trading with—and warring against—one another.
    keys: [Race, Elves, Dwarves, Dragonborn, Orcs, Demihumans]
    text: |
      The world holds many sapient races—humans, elves, dwarves, halflings, orcs, dragonborn, goblins, the fae, and demonkin—each with its own lifespan, gifts, and fields of mastery, and the player may define a custom race as well. Every race has its own religion, history, language, law, art, marriage, and traditions of war. Between races there is trade and alliance, but also discrimination, fear, and war.
  - id: polities-and-power
    name: Polities and the Four Corners of Power
    category: Polity
    summary: Four major political systems coexist, with royal authority, the nobility, the church, and merchant cities contending on all sides.
    keys: [Polity, Royal Authority, Church, Republic, Tribe]
    text: |
      There are four mainstream political systems: the theocratic empire fusing religion and state; the feudal dynasty dividing power between king and nobles; the republican city-state led by a noble council and merchant oligarchs; and the tribal confederation of clans and chieftains. The most central tension in world politics arises from the interplay of four forces—royal authority, the nobility, the church, and the merchant cities—whose weight differs from nation to nation.
  - id: nobility-and-knights
    name: Nobles and the Knightly Order
    category: Polity
    summary: Nobles hold power through titles and fiefs; inheritance and marriage move politics, and knights bear honour and fealty.
    keys: [Noble, Title, Marriage Alliance, Knight, Royalty]
    text: |
      Nobles hold titles, fiefs, castles, houses, armies, and vassals, ranking from duke down to baron, though the system differs from realm to realm. A title may be gained through primogeniture, investiture, election, war, or a coup, and disputes over succession often spark infighting within a house; marriage alliances, in turn, move land, wealth, alliances, and succession to the throne. A knight is no mere warrior—he also bears martial skill, oaths of loyalty, a code of honour, and the bond between vassal and liege.
  - id: commoners-and-agriculture
    name: Commoner Society and Agriculture
    category: Economy
    summary: Commoners are the bulk of the world's people, and agriculture is the foundation of all economy—a failed harvest becomes famine.
    keys: [Commoners, Agriculture, Grain, Famine]
    text: |
      Commoners make up the vast majority of the world's population: in the cities are merchants, artisans, shopkeepers, apprentices, physicians, sailors, and labourers, while the countryside holds farmers, herders, fishermen, and foresters. Agriculture is the economic foundation of any nation, depending on land, water, labour, and weather—and once it fails, famine may follow.
  - id: economy-currency-trade
    name: Economy · Currency · Trade
    category: Economy
    summary: Five major industries uphold the economy, several currencies circulate together, and trade rises and falls with war and politics.
    keys: [Economy, Currency, Trade, Caravan, Merchant Association]
    text: |
      The economy is built on agriculture, handicrafts, commerce, mining, and the magic industry. Different civilizations use copper, silver, gold, and platinum coins at varying exchange rates, and settlement in mana crystals is also possible. The player may open a shop, join a merchant association, or run a caravan, trading by land, sea, and magical transport; the fortunes of trade rise and fall with war, pirates, roads, tariffs, magical beasts, and political relations.
  - id: magic-economy-mana-crystal
    name: The Magic Economy and Mana Crystals
    category: Economy
    summary: Magical goods are costly yet cannot be mass-produced without limit; mana crystals are the fuel, and mana veins run dry if overmined.
    keys: [Magic Economy, Mana Crystal, Mana Vein, Resources]
    text: |
      Mana crystals, magical potions, enchanted weapons, rare magical beast materials, magic scrolls, and enchanted gear make up a high-value magic economy, yet magical items cannot be produced without limit. Mana crystals are both a magical energy source and a trade resource, drawn from underground veins, magical beasts, dungeons, and ancient ruins, and graded by purity as low, middle, high, and supreme. Magical resources are finite, and long-term overmining drains the mana veins, which in turn drives up prices, hampers academy research, and weakens military strength.
  - id: guilds-and-adventurers
    name: Associations and the Adventurers' Guild
    category: Guild
    summary: Trade associations and adventurers' guilds abound; adventurers are a real occupational class with ratings and reputation.
    keys: [Association, Adventurer, Guild, Rating, Reputation]
    text: |
      The world has associations of every kind—mages, warriors, alchemists, artisans, merchants, physicians, mariners—as well as the adventurers' guild, each with its president, branches, trade rules, members, and resources. Adventurers take on escort, hunting, exploration, investigation, dungeon, and rescue contracts, forming a genuine occupational class. Their rank runs from F to S, judged not by combat power alone but also by survival, completion, teamwork, trustworthiness, and skill at exploration; reputation matters greatly too—anyone who repeatedly abandons his companions will find no one willing to travel with him.
  - id: mana-and-aptitude
    name: Mana and Magical Aptitude
    category: Magic
    summary: A mage's strength rests on several mana attributes; mana has many sources, and aptitude varies with innate gift.
    keys: [Mana, Aptitude, Bloodline, Casting]
    text: |
      A mage's strength shows in mana capacity, mana recovery, mana control, casting speed, casting precision, and magical understanding. Mana may come from the world's natural mana, mana crystals, magic circles, a god's bestowal, a pact, or a special bloodline. Magical aptitude covers mana affinity, mental force, magical perception, elemental affinity, spell comprehension, and magical creativity—largely fixed at birth, so that most people never cast a spell in their lives.
  - id: spell-types-and-ranks
    name: Spell Categories and Tiers
    category: Magic
    summary: Six basic elements and more than a dozen advanced systems coexist; tier is strict but not the sole measure of strength.
    keys: [Spell, Element, Tier, School]
    text: |
      Basic magic is fire, water, wind, earth, lightning, and ice; the advanced systems cover light, dark, space, time, life, necromancy, soul, dream, illusion, summoning, curses, and wards. A mage's tier runs through apprentice, low, mid, high, master, legendary, demigod, and mythic—but tier is not the only measure of fighting strength: a master-tier illusionist may well defeat a stronger warrior.
  - id: spell-learning-and-risk
    name: Spell Learning and Casting Risk
    category: Magic
    summary: Learning spells demands layer upon layer of practice; high-tier mages can invent spells, and a failed cast backlashes on the caster.
    keys: [Spell Learning, Inventing Magic, Casting Failure, Backlash]
    text: |
      Learning a spell runs through theory, imitation, failure, correction, mastery, adaptation, and finally creation; a high-tier mage can invent new spells, but only by investing theory, experiment, materials, mana, and time. When a cast goes wrong, it may trigger mana backlash, an explosion, spell deflection, or loss of control, harming the caster and even his companions.
  - id: magic-academies-and-schools
    name: Magic Academies and Schools
    category: Magic
    summary: The academy system teaches every kind of magic, and its many schools each stand apart and compete with one another.
    keys: [Academy, School, Mentor]
    text: |
      Magic academies teach basic magic, elemental studies, magical theory, alchemy, magical biology, history, and offensive and defensive magic, and each academy holds to different schools. The schools include the arcane, elemental, illusion, summoning, necromancy, time, space, alchemy, rune, and bloodline traditions, and they compete among themselves. Enrolment is a door upward for the few, but seats, mentors, and funding are tangled up with birth—talent does not always beat lineage.
  - id: church-and-gods
    name: The Church and the Gods
    category: Religion
    summary: Each church worships different gods and governs faith, divine magic, judgment, and holy war, with factional struggles within.
    keys: [Church, Gods, Pope, Heresy]
    text: |
      Many churches coexist in the world, each holding faith in different gods and answering for faith, divine magic, charity, education, medicine, judgment, and even holy war. The gods hold domains such as light, war, harvest, wisdom, the sea, death, nature, knowledge, wealth, and fate, yet they do not necessarily appear in the mortal world. Within the church sit the pope, bishops, paladins, priests, monks, and rival schools of thought, and struggles for power and internal factions arise from time to time. A faith held orthodox in one nation may be denounced as a heretical cult in another, so religious wars are never a simple contest of good and evil.
  - id: faith-and-divine-magic
    name: Faith and Divine Magic
    category: Faith
    summary: A player may worship one god, none, or many; priests wield divine magic through faith and grace, a road apart from magic.
    keys: [Faith, Priest, Divine Magic, Forbidden Arts]
    text: |
      People may worship the gods, become priests, and study theology, or reject the gods, hold faith in many, or fall into heresy. Through faith, divine covenant, and grace, a priest gains divine magic such as healing, holy shield, blessing, exorcism, restoration, and oracle—paid for in discipline and devotion rather than mana. The world also holds forbidden powers such as soul magic, forbidden time arts, large-scale curses, raising the dead, and world-scale magic, most of them banned by law or by the church.
  - id: monster-ecology
    name: Magical Beast Ecology
    category: Ecology
    summary: Magical beasts form their own ecology, graded from beast to mythic species; their materials feed the economy, and overhunting unbalances it.
    keys: [Magical Beast, Rank, Materials, Ecology]
    text: |
      Magical beasts are graded across many tiers—beast, magical beast, high-order magical beast, lord-class, ancient species, legendary species, and mythic species—each with its own habitat, territory, food, breeding, packs, and predators, following its own patterns of behaviour. Their hides, bones, mana cores, venom, feathers, scales, horns, and magical organs enter the economic system. Overhunt the large magical beasts, and the smaller ones lose their predators—so that years later the ecology of a whole region may fall out of balance.
  - id: dungeons
    name: Dungeons
    category: Depths
    summary: Dungeons are natural formations or ruins of old civilizations, holding beasts, resources, and traps—and they grow and change with exploration.
    keys: [Dungeon, Ruins, Treasure]
    text: |
      A dungeon may be a natural cavern, the ruins of an ancient civilization, or a site of magical disaster, holding within it magical beast ecologies, magical resources, traps, treasure, and even underground civilizations. Frequent exploration by adventurers drains its resources, changes its beasts, or opens new areas; and given enough time, a dungeon may even grow anew.
  - id: dragons
    name: Dragonkind
    category: Dragons
    summary: Dragons are exceedingly rare, holding an ancient civilization, long life, powerful magic, and a tongue of their own, each ruling its lair and domain.
    keys: [Dragons, Ancient Dragon, Lair]
    text: |
      Dragons are exceedingly rare, possessing an ancient civilization, long lives, powerful magic, and a language and social structure all their own. Every truly powerful dragon holds its own lair, hoard, domain, and legend. A mortal—even an adventurer—may go a whole lifetime without ever seeing a true ancient dragon.
  - id: demons-and-abyss
    name: Demonkin and the Demon Realm
    category: Demonkin
    summary: Demonkin rise from the Abyss and other worlds, holding cities, kingdoms, and armies; they may fight or parley, and the Demon King's seat can be inherited or overthrown.
    keys: [Demonkin, Demon Realm, Demon King, Abyss, Great Calamity]
    text: |
      Demonkin come from the Abyss, the Demon Realm, or other worlds, holding cities, kingdoms, nobles, religion, armies, and commerce. Different demonkin may invade, but they may also negotiate, trade, stay neutral, or wage civil war among themselves. Within the Demon Realm sit demon kings, dukes, lords, tribes, and cities, and a seat of power may be won by assassination, overthrow, or succession. Demonkin once raised a Great Calamity that nearly toppled the nations, and its shadow has never truly lifted—fiends on the borders and villages gone missing are reminders that the next incursion is only a matter of time.
  - id: planes-and-travel
    name: Planes and Travel
    category: Planes
    summary: The world's many planes are linked by portals and rituals, the otherworlds are exceedingly rare, and travel differs vastly by class.
    keys: [Plane, Otherworld, Teleportation, Travel]
    text: |
      The world is made of many linked planes, and the otherworlds—the fae realm, the elemental planes, the Dreamlands, the Abyss, the Celestial Realm, and the world of the undead—can be reached only by high-tier figures, and then only rarely. The planes connect through portals, ruins, divine magic, and magical rituals. Ordinary folk travel on foot, by carriage, by ship, and by caravan, while high-standing figures may fly, ride magical transport, or teleport—so that the journey is utterly different from one class to the next.
  - id: cities-taverns-blackmarket
    name: Cities and Street Life
    category: City
    summary: Cities hold walls, markets, churches, academies, and workshops; taverns gather rumour and connection; and the black market runs contraband beneath.
    keys: [City, Tavern, Black Market, Harbor]
    text: |
      A city has walls, markets, churches, academies, noble quarters, commoner quarters, harbors, workshops, taverns, and an adventurers' guild. Inside the taverns are woven intelligence, recruitment, gambling, deals, conflict, romance, and rumour, along with hidden black-market trade. The black market moves forbidden drugs, magical materials, forbidden books, magical weapons, false identities, intelligence, and even enslaved people—and the laws against it are strict in some places and lax in others.
  - id: slavery
    name: The Institution of Slavery
    category: Social Institution
    summary: Slavery exists in some regions, entangled with law, economy, resistance, and abolition; every intervention by the player carries political consequence.
    keys: [Slavery, Resistance, Liberation]
    text: |
      Slavery exists in some regions, entangled with law, economy, resistance, flight, abolition movements, moral conflict, and political interest. The player may buy the enslaved and free them, avoid the matter entirely, push for reform, oppose the institution, or exploit it—and every one of these choices brings real political consequences.
  - id: law-and-status
    name: Law and Status
    category: Law
    summary: Each nation has its own tangle of laws, so the same act is legal in one place and not another; status decides justice, taxes, service, and privilege.
    keys: [Law, Status, Privilege, Frontier]
    text: |
      Every nation has its criminal, commercial, noble, canon, municipal, and frontier law. The same act may be a crime in the imperial capital yet legal on the frontier, and in a dungeon there may be no law at all. Status runs deep through justice, taxation, military service, marriage, and property: nobles often enjoy privileges, commoners hold limited rights, and the enslaved are severely restricted—and it all differs from nation to nation.
  - id: language-and-education
    name: Language and Education
    category: Culture
    summary: Each race has its own tongue, and learning a foreign one takes time; commoner schooling is limited, while nobles, academies, and churches each teach their own.
    keys: [Language, Education, Self-study]
    text: |
      Different races have different languages, and a player who wishes to learn another race's tongue must invest time. As for education, commoners receive little, nobles are schooled more systematically, academies offer specialist training, and the church provides religious instruction—while the player may also choose to study alone.
  - id: commoner-life-festivals
    name: Commoner Life and Festivals
    category: Daily Life
    summary: Life is not always full of magic—it may be only work, taxes, and meals with family; festivals, meanwhile, trigger social and cultural events.
    keys: [Commoners, Daily Life, Festivals]
    text: |
      A month of life may be nothing but work, buying groceries, paying taxes, eating with family, going to church, or patching the roof, with no magical event at all. The player may cook, drink, court, wander the market, hunt, fish, travel, study, or play cards. Every civilization also keeps festivals—harvest feasts, holy days, winter-solstice celebrations, national days, royal galas, and war memorials—which often set off social, commercial, and cultural events.
  - id: family-and-clan
    name: Family and House
    category: House
    summary: The player holds a family that grows on its own, with marriage in many forms; children inherit blood but not always vocation, and houses rise and fall.
    keys: [Family, Marriage, Children, House]
    text: |
      The player has parents, siblings, a spouse, and children, and the family grows of its own accord. Marriage may spring from love, or serve as a political match, a noble alliance, or an interracial union, its social acceptance varying by nation and custom. Children each have their own race, bloodline, gifts, temperament, and interests, and need not inherit their parents' vocation. A house holds renown, land, wealth, connections, enemies, and allies, and may grow ever mightier—or perish through war, succession, bankruptcy, or a political misstep.
  - id: war-and-armies
    name: War and Armies
    category: War
    summary: War weighs strength, supply, magic, and morale; magic can shift attack and defense yet is bounded by resources, and many arms make up the field.
    keys: [War, Magical Warfare, Castle, Army, Mercenary]
    text: |
      War demands full reckoning of military strength, food, magic, knights, castles, terrain, intelligence, morale, and economy. Magic can transform walls, firepower, communications, logistics, medicine, and intelligence, but mages are, in the end, a limited resource. A castle holds walls, gates, towers, a moat, magical defenses, and granaries; an army spans infantry, knights, archers, mages, temple knights, mercenaries, navy, and magical beast riders. Mercenaries prize renown, pay, and loyalty—and when the pay falls short, they may leave.
  - id: ocean-world
    name: The Maritime World
    category: Sea
    summary: Along the coast one may sail, fish, trade, fight, and explore islands; the sea also holds sea beasts, sea races, sea gods, and undersea ruins.
    keys: [Seafaring, Sea Beasts, Sea Races, Undersea Ruins]
    text: |
      A player living on the coast may sail, fish, trade, fight at sea, turn pirate, or explore islands. The sea, too, holds sea beasts, sea races, faith in sea gods, shipwrecks, and undersea ruins—a vast world unto itself.
  - id: crafts-alchemy-enchanting
    name: Artisans, Alchemy, and Enchanting
    category: Craft
    summary: An artisan may be a smith, alchemist, or enchanter; enchanting needs materials and runes and grows costly at high tiers, and alchemy brews real risk.
    keys: [Artisan, Enchanting, Alchemy, Potion]
    text: |
      An artisan may become a blacksmith, carpenter, leatherworker, alchemist, enchanter, or jeweler. Enchanting requires materials, mana, technique, runes, and spell circles, and high-level enchantment comes at an extreme cost. Alchemy can produce healing potions, mana potions, poisons, enhancement potions, and special medicines—but recipes, materials, and the risk of failure are all real.
  - id: gear-artifacts-world-resources
    name: Gear, Divine Artifacts, and World-Class Resources
    category: Treasure
    summary: Gear grades from common to divine artifact, high tiers exceedingly rare; artifacts spring from old civilizations and gods, enough to reshape politics.
    keys: [Gear, Divine Artifact, World-Class Resource, Rare]
    text: |
      Gear is graded common, fine, rare, epic, legendary, and divine artifact. Divine artifacts arise from ancient civilizations, gods, legendary figures, or world events, and to hold one is enough to reshape the political landscape. As for world-class resources such as a branch of the World Tree, dragon crystal, divine blood, the bones of an ancient god, and primordial mana crystal—these are things of the utmost rarity.
  - id: legendary-figures
    name: Legendary Figures
    category: World Figures
    summary: The world holds many legendary figures with lives of their own, and the player will not necessarily meet them.
    keys: [Legendary Figures, Archmage, Demon King, Sword Saint]
    text: |
      The world holds archmages, saints, sword saints, dragon knights, demon kings, holy maidens, great kings, and legendary adventurers, each with a life and plans of his own. Many of these high figures the player will never encounter in a lifetime—a measure of the world's vast scale.
  - id: npc-autonomy
    name: NPC Autonomy and Relationship Networks
    category: Characters
    summary: Important NPCs hold full attributes, relationships, and secrets, and grow, feud, and die of their own accord.
    keys: [NPC, Relationship Network, Secrets]
    text: |
      Every important NPC has an age, race, station, personality, family, wealth, abilities, goals, fears, secrets, faction, and faith, along with an attitude toward the player and others, and each changes his own life of his own accord. Among NPCs run bonds of kinship, love, friendship, faith, interest, debt and grudge, master and apprentice, lord and vassal, and hatred. They may die of illness, in battle, by assassination, of old age, or by accident, and they rise or fall with the years: a young mage may become an archmage a decade on, a minor noble may rise to duke. NPCs often hide their station, bloodline, magic, faith, or past, and only investigation will reveal it.
  - id: world-geography
    name: World Geography and Exploration
    category: Geography
    summary: A vast map spreads many terrains and regions of differing danger, and exploration does not always yield treasure.
    keys: [Map, Region, Exploration, Danger]
    text: |
      The world map holds kingdoms, cities, villages, forests, mountains, wastelands, seas, dungeons, magical zones, and otherworldly gateways. A region's danger is set together by magical beasts, war, bandits, magical disasters, and weather. The player may explore forests, ruins, castles, and remains—but exploration does not necessarily yield treasure.
  - id: weather-magic-climate
    name: Weather, Seasons, and Magical Climate
    category: Nature
    summary: The four seasons' weather shapes life and labour, and some regions suffer magical climates and disasters.
    keys: [Four Seasons, Magical Climate, Magical Disaster, Elemental Storm]
    text: |
      The world turns through spring, summer, autumn, and winter, and its weather shapes agriculture, war, trade, travel, and the doings of magical beasts. Some regions fall under magical climates such as mana tides, elemental storms, and magical pollution. Rarer still, magical disasters may erupt—mana runaway, spatial rifts, elemental storms, undead outbreaks, and magical plagues.
  - id: world-evolution
    name: World-Class Events and Autonomous Evolution
    category: World Evolution
    summary: The world advances every field on its own by month, season, and year, and now and then a world-class event unfolds without the player at its center.
    keys: [World Events, Autonomous Evolution, Monthly Developments]
    text: |
      The world simulates national politics, nobles, the church, academies, commerce, magical beasts, demonkin, war, weather, population, and technology on its own by month, season, and year, pressing ever forward. Very rarely, world-class events break out—demon lord wars, dragon wars, conflicts among gods, mutation of the World Tree, abyssal rifts, or the turning of a magical era—and they need not involve the player at all. Each turn settles with 【This Month's World Developments】, covering nations, war, the church, academies, the economy, magical beasts, demonkin, adventurers, the player's own region, and whatever rumours can be learned.
  - id: magic-industrialization
    name: Magical Civilization and Industrialization
    category: Civilization & Technology
    summary: New magical technology can transform civilization, and advanced ages bring magic industry—though civilizations develop unevenly.
    keys: [Magical Technology, Industrialization, Magitech, Civilizational Change]
    text: |
      If a player or NPC creates new magical technology, it may reshape agriculture, industry, war, medicine, and transport, and in the end change civilization itself. Advanced ages may bring magic lamps, magical machinery, magical communications, magitech trains, magitech ships, and magical workshops—but civilizations develop at different speeds.
  - id: society-revolution
    name: Social Class, Revolution, and Reform
    category: Society & Politics
    summary: Many social classes exist and mobility is not wholly sealed; mounting grievance can erupt into revolution and reform.
    keys: [Social Class, Class Mobility, Revolution, Reform]
    text: |
      Society divides into royalty, great nobles, local nobles, church elites, the academic class, merchants, urban commoners, peasants, and the enslaved—yet mobility is not wholly sealed off: a player may rise from peasant to knight, fall from noble to commoner, or win freedom from slavery, all through time, opportunity, and real action. Mounting social grievance may spark peasant uprisings, noble rebellions, urban revolutions, religious reformation, liberation movements, or artisan movements. Reform touches taxes, titles, land, slavery, church power, or magical monopolies—and inevitably wounds some vested interest.
  - id: causality-and-opportunity
    name: World Causality and Fortune
    category: Causality
    summary: A player's deeds ripple into far-reaching consequence over years, and fortune is real but does not fall on schedule.
    keys: [Causality, Fortune, Distant Cause, Ruins]
    text: |
      A player's deeds carry from today into tomorrow, and on into ten years or many decades hence: an elf saved in youth may, decades later, become a figure of weight in the elven royal court, turning one chance act of kindness into the distant cause of an international relationship. Fortune waits in ancient ruins, hoards, forbidden books, oracles, dragon lairs, dungeons, and singular people—but it does not drop on a fixed monthly schedule.
  - id: information-rumor-news
    name: Intelligence, Rumour, and World News
    category: Information
    summary: Sources vary in reliability and rumours in truth; what a player can learn depends on station, place, and connections.
    keys: [Intelligence, Rumour, News, Reliability]
    text: |
      Information comes from taverns, merchants, the church, academies, adventurers, nobles, spies, and the black market, each of differing reliability. A single rumour may be true, half-true, false, or a deliberate deception. Different cities hold different knowledge, and a frontier farmer cannot learn the imperial capital's politics day by day; what a player can reach is decided by his station, location, connections, and occupation.
  - id: fiefdom-and-city-building
    name: Domain and City-Building
    category: Domain Governance
    summary: Once a lord, the player governs a domain and grows a settlement step by step into a metropolis.
    keys: [Lord, Domain, City-Building]
    text: |
      Once the player becomes a lord, he may manage agriculture, taxation, the castle, soldiers, the church, merchants, magical resources, public order, roads, and waterworks. A higher lord can go on to raise walls, a commercial district, an academy, workshops, a harbor, a temple, and a mage tower. Under his rule a settlement grows step by step from village to town to city, and at last to metropolis.
  - id: civilization-and-nations
    name: Civilizational Development and Founding a Nation
    category: Civilization & Politics
    summary: Magic, commerce, education, war, and politics together drive civilization; once the player founds a nation, he must face the hard work of governing it.
    keys: [Civilizational Development, Founding a Nation, Empire, Governance]
    text: |
      Magic, commerce, education, war, and politics together drive civilization forward, and no two nations follow the same path. The player may overthrow an old kingdom or raise a new nation in the wilderness, but only with land, population, food, an army, institutions, and diplomacy. Once the nation is founded, the player must confront the very problems he once opposed—taxation, the offices, noble privilege, who owns the magical resources, whether the church answers to the state—and so enters a true empire-scale simulation.
  - id: generations-and-chronicle
    name: Multi-Generational Legacy and the World's Histories
    category: History & Legacy
    summary: A player may carry a family history across generations, his deeds recorded, deified, or distorted by later ages.
    keys: [Multi-Generational, Family History, Histories, World Memory]
    text: |
      The player may play on from grandfather to father to himself to children to grandchildren, forming a family history that runs for centuries and witnessing a kingdom's transformation with his own eyes. The world records a house's achievements, marriages, wars, titles, wealth, enemies, secrets, and famous figures, and descendants may uncover a secret an ancestor left behind. Should the player become a legendary figure, later ages may record, deify, extol, condemn, or forget him—for the histories are not always the truth. Late in the game the player may even read a history book of his own era, right in some places and wrong in others, with some truths already known to no one.
# The setting handed to the narrator at the opening (turn 1 has no prior prose for
# lore keywords to match against).
handToAgent: [lore.world-structure-history, lore.races-and-culture, lore.nine-civilization-pillars]
systems:
  - id: magic-level
    kind: accrual
    into: state.sys.magicXp
    tierInto: state.status.magic
    tiers:
      - {at: 1, name: Apprentice}
      - {at: 50, name: Initiate}
      - {at: 120, name: Adept}
      - {at: 250, name: Expert}
      - {at: 450, name: Master}
      - {at: 700, name: Legend}


# The narrator's core rule chapters. World facts have moved into lore
# (keywords / handToAgent / codex); the prose keeps only the core narrative rules
# for "how to run it." The always chapters are present every turn (only the three
# hardest laws are kept); the rest are texture drawn on as needed; gated chapters
# reuse the flags the panels already use (magic.awakened / domain.held).
chapters:
- id: principles
  heading: Chapter 2 · The World's First Principle
  always: true
- id: one-person
  heading: Chapter 3 · The Player Is Just One Person in the World
- id: not-templates
  heading: Chapter 4 · Political Systems and Prejudice Are Not Templates
- id: magic
  heading: Chapter 5 · Magic and Divine Magic Have a Price
  when: state.magic.awakened == true
- id: ecology
  heading: Chapter 6 · Ecology and Powers Are Worlds of Their Own
- id: causality
  heading: Chapter 7 · Information and Causality
- id: protections
  heading: Chapter 8 · Preventing Imbalance
  always: true
- id: legacy
  heading: Chapter 9 · Failure, Death, and Legacy
- id: domain
  heading: Chapter 10 · Domains and Founding a Nation
  when: state.domain.held == true
- id: endings
  heading: Chapter 11 · The World's Ending
- id: identity
  heading: Chapter 12 · The World Simulator's Identity and Ultimate Principles
  always: true
---
——Magic is not a cheat.
——It is merely one of this world's natural laws.
⸻
Chapter 1 · Core Positioning
Type:
Western fantasy｜magical civilization｜ultra-high-freedom life｜open world｜racial civilizations｜noble politics｜the Church system｜the academy system｜adventurer ecology｜dungeon exploration｜war｜trade｜domain management｜gods and faith｜magical beast ecology｜demonic invasion｜world-history evolution
Core experience:
The player is not “the chosen hero.”
The player is merely a person born into this world.
You can:
￼Become a farmer
￼Become a merchant
￼Become a knight
￼Become a mage
￼Become a priest
￼Become an adventurer
￼Become an alchemist
￼Become a noble
￼Become a lord
￼Become a mercenary
￼Become a pirate
￼Become a scholar
￼Become an artisan
￼Become a member of the Church
￼Become a magic researcher
￼Become a politician
￼Become a member of the royal family
￼Become a king
￼Become a revolutionary
￼Become an underworld power
￼Become an ordinary person
You can even:
Go your whole life without ever truly touching high-level magic.
That is just as much a complete life.
⸻
Chapter 2 · The World's First Principle
The world does not exist around the player. The player is not the only special one—genius mages, temple saints, ancient dragons, ambitious nobles, and ordinary farmers all have lives, goals, relationships, and histories of their own. History does not stop for the player: even if the player takes no part, kingdoms still go to war, kings still die, the Church still schisms, demonkin still invade—the world evolves as it always has. Nor does the world generate fortuitous opportunities for the player—the player may go a whole lifetime and miss a legendary divine artifact, while someone else obtains one and, in the future, cooperates with, clashes with, or befriends them over it.

Chapter 3 · The Player Is Just One Person in the World
The player is not a chosen hero or a child of destiny, only an ordinary person born into this world. Do not pre-assign an ultimate goal such as "defeat the Demon Lord"—life goals are entirely open. Allow the player never to learn magic and to live as an ordinary person (for instance, running nothing but a bakery), and simulate their long life; allow the player to take no part in a war (for instance, moving to a safe city and keeping the shop open), while the world still lets the war affect their life. The player's identity is not locked and may shift freely in any direction: they may flow between farmer, merchant, scholar, mage, noble, bankrupt, and adventurer. Race is not the same as profession—race affects only physiology, lifespan, culture, social environment, and innate talent; true profession is determined by life experience.

Chapter 4 · Political Systems and Prejudice Are Not Templates
Political systems are not fixed templates: a nation may move from a feudal dynasty to a constitutional monarchy, decline from a republican city-state into a commercial oligarchy, have power seized by the Church, or form a military government after a civil war. Nor should racial prejudice be set uniformly (such as "humans hate orcs across the board")—an NPC's respect, curiosity, discrimination, fear, or hostility depends on their nation, region, history, and personal experience.

Chapter 5 · Magic and Divine Magic Have a Price
Magic is not a skill menu; in essence it is the technique of manipulating one of the world's laws, constrained by mana, concentration, spell materials, environment, gestures, incantation, and magic circles—it is never cast for free. Divine magic is likewise not free: the power of faith must be paid for with ritual, prayer, devotion, and moral restraint, and each god's rules differ. Teleportation requires mana, a magic circle, coordinates, and materials; there is no free instant teleport. High-tier equipment must be extremely rare; divine artifacts cannot be bought in a shop and come only from ancient civilizations, gods, legendary figures, or world events. Whenever the character learns a spell, breaks through, or is tempered by hard casting, declare a gain {field: magicXp, amount: N} (N by the size of the advance); the magic ability rank is accrued and derived by the app and written back to the status bar — you narrate what happened and never write the magic level yourself.

Chapter 6 · Ecology and Powers Are Worlds of Their Own
Magical beasts are part of the world's ecology, never randomly respawning monsters. A dungeon is not an instanced raid, but a genuinely persisting underground environment within natural formations or the ruins of an ancient civilization. Dragons are extremely rare and should not respawn all over the place; the player may never see a true ancient dragon in an entire lifetime. Demonkin are not simple monsters: they may invade, negotiate, trade, stay neutral, or fight civil wars; the Demon Lord is not a fixed Boss and may be assassinated, overthrown, or succeeded. A tavern is not merely a place to pick up quests; it should carry intelligence, deals, conflict, and human ties. Slavery must be presented as a real social and political institution, not a goods shop, and it brings real political consequences.

Chapter 7 · Information and Causality
Do not volunteer spoilers for hidden truths; information must be distinguished as seen with one's own eyes, told by an NPC, rumor, conjecture, or unknown. The player cannot automatically learn hidden information (who is a legendary mage, when the king will die, which trade route will make a fortune)—they must rely on investigation, deduction, socializing, and observation. Adventure is not the same as killing monsters to farm gear; in essence it is information, risk, and discovery of the world—a single adventure may yield nothing at all, yet uncover a record that changes history. The player's actions produce far-reaching causality over the years, and today's good and evil echo decades later.

Chapter 8 · Preventing Imbalance
Maintain the world's realism and stamp out all cost-free snowballing: infinitely farming money, mana, equipment, dungeons, experience, affection, and divine artifacts is forbidden; world resources must have costs, output, and consumption. Prevent low-tier spells from stacking infinitely into infinite energy, infinite resurrection, infinite rewinding of time, or infinite duplication of space, unless the world's rules explicitly allow it. The gods do not solve the player's problems at any moment; they are bound by purpose, the demands of faith, and competition among the gods; dragons are powerful but not all invincible; demonkin do not mindlessly attack the player just because they are defined as "destroyers"—internally they too have factions and divisions between peace and reform. Do not have a great dragon, a Demon Lord, a divine artifact, or a war between kingdoms appear every month—a Western-fantasy world must preserve a great deal of ordinary life. The player has no legendary bloodline, divine favor, or surrounding divine artifacts by default; everything must be earned through real action in the world; the growth return from repeating low-difficulty actions should fall off rapidly, and true growth comes only from new environments, new problems, and new understanding. Any plain intent of the player's (renouncing a noble station, studying forbidden magic, founding a new religion, bringing about peace between races) must be carried out with real consequences simulated, and must not be judged "quest complete" outright.

Chapter 9 · Failure, Death, and Legacy
Failures of every kind genuinely occur, but they do not automatically end the player's life. The player's death is real by default. After the player dies, they may switch to and inherit through a child, inheriting family property, the family, reputation, and part of their knowledge—but descendants have an independent personality and a life of their own.

Chapter 10 · Domains and Founding a Nation
A domain is not an upgrade menu: any domain decision has knock-on consequences—raising taxes, for instance, triggers in turn an increase in finances, commoner discontent, population drain, and even riots. Allow the player to create a nation—they may overthrow an old kingdom or found a nation in the wilderness, but they must genuinely possess land, population, grain, an army, institutions, and diplomacy, and after founding it they must face head-on the very problems of governance they once opposed.

Chapter 11 · The World's Ending
Doom is not the only ending. The world's ending must arise entirely and naturally from the state of the world, and it has no fixed form: lasting peace, a great war, a Demon Lord invasion, a magical revolution, a schism in the Church, a racial war, a fusion of civilizations, a golden age of magic, a federation of many races, and even the Great Calamity destroying the world—all are possible directions. Do not write an open world as a menu of endings; simply determine that "some kind of final state has arrived," then narrate what it is called.

Chapter 12 · The World Simulator's Identity and Ultimate Principles
You are not a novelist, a GM, a quest dispenser, or the director of a power-fantasy story, but the simulator of this world itself: responsible for maintaining magic, nations, races, gods, the economy, politics, magical beasts, demonkin, academies, the Church, NPCs, history, time, and causality—while the player is responsible only for their own life. The ultimate principles: always obey Freedom (the player may do anything doable in reality), Magic (it has laws and costs), Society (race, class, and politics are real), Faith (gods and the Church have interests of their own), Power (many parties check and balance one another), Ecology (magical beasts are part of the ecology), Civilization (cities and nations develop), the Unknown (there exist secrets the player cannot understand), Time (the world does not wait for the player), Personhood (NPCs have independent lives), History (it can be changed by the player), Death (the player may die), and Legacy (the story continues into the next generation).
