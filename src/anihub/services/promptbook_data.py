"""The built-in catalogue of the prompt builder: slots (the paragraphs of a prompt, in the order they are written) and, for each
slot, categories with ready-made tags.

Why this order: Stable Diffusion weighs the beginning of a prompt most and reads it in chunks, so a prompt that goes
quality -> style -> who -> appearance -> clothing -> pose -> camera -> background -> light keeps the important things first and
the scenery last. That is how well-made prompts of the Danbooru-tag models (SD 1.5 anime, SDXL, Pony, Illustrious) are written.

Format of RAW: a header line `## slot | key | English | Русский | x` starts a category (x = only one tag of it at a time);
the next line lists its tags as `tag=русское название; tag; tag=...` (the tag itself is always what goes into the prompt).
"""
from __future__ import annotations

# (key, English, Русский, negative?, per-character?) in the order the paragraphs are written. "per-character":
# with more than one active character (ui/prompt_builder.py's character switcher), this slot gets one instance
# per character instead of being shared -- character/appearance/expression/clothing/pose are naturally about ONE
# specific character, "who and how many" (subject) and everything after pose is scene-level and stays shared.
SLOTS = [
    ("quality", "Quality", "Качество", False, False),
    ("style", "Style and medium", "Стиль и техника", False, False),
    ("subject", "Who and how many", "Кто и сколько", False, False),
    ("character", "Character", "Персонаж", False, True),
    ("appearance", "Appearance", "Внешность", False, True),
    ("expression", "Expression", "Эмоции", False, True),
    ("clothing", "Clothing", "Одежда", False, True),
    ("pose", "Pose and action", "Поза и действие", False, True),
    ("camera", "Camera and composition", "Кадр и композиция", False, False),
    ("background", "Background and place", "Фон и место", False, False),
    ("lighting", "Light, time, mood", "Свет, время, настроение", False, False),
    ("extra", "Extra (LoRA, own tags)", "Прочее (LoRA, свои теги)", False, False),
    ("neg_quality", "Bad quality", "Плохое качество", True, False),
    ("neg_anatomy", "Bad anatomy", "Плохая анатомия", True, False),
    ("neg_artifacts", "Text and artifacts", "Текст и артефакты", True, False),
    ("neg_unwanted", "Unwanted things", "Нежелательное", True, False),
]

RAW = r"""
## quality | basic | Basic quality | Базовое качество
masterpiece=шедевр; best quality=лучшее качество; high quality=высокое качество; highres=высокое разрешение; absurdres=сверхвысокое разрешение; ultra-detailed=сверхдетально; very aesthetic=очень эстетично; amazing quality=потрясающее качество; newest=новейшее; 8k=8K; sharp focus=чёткий фокус
## quality | detail | Detail | Детализация
intricate details=сложные детали; extremely detailed=очень подробно; detailed eyes=детальные глаза; detailed face=детальное лицо; detailed hair=детальные волосы; beautiful detailed eyes=красивые детальные глаза; detailed skin=детальная кожа
## quality | pony | Pony score tags | Теги для Pony
score_9; score_8_up; score_7_up; source_anime; source_cartoon; rating_safe

## style | medium | Medium | Техника
anime=аниме; anime screencap=кадр из аниме; illustration=иллюстрация; digital art=цифровой рисунок; digital painting=цифровая живопись; watercolor (medium)=акварель; oil painting=масло; sketch=набросок; lineart=контурный рисунок; monochrome=монохром; greyscale=оттенки серого; manga=манга; comic=комикс; flat color=плоские цвета; cel shading=сел-шейдинг; pixel art=пиксель-арт; chibi=чиби; 3d=3D; realistic=реализм; photorealistic=фотореализм; concept art=концепт-арт; traditional media=традиционные материалы
## style | look | Look and era | Вид и эпоха
retro artstyle=ретро-стиль; 1990s (style)=стиль 90-х; 1980s (style)=стиль 80-х; official art=официальный арт; cinematic=кинематографично; soft focus=мягкий фокус; painterly=живописно; minimalist=минимализм; ukiyo-e=укиё-э; art nouveau=ар-нуво; cyberpunk=киберпанк; steampunk=стимпанк
## style | effects | Effects | Эффекты
bloom=свечение; chromatic aberration=хроматическая аберрация; film grain=плёночное зерно; lens flare=блик объектива; motion blur=размытие движения; sparkle=искры; glowing=свечение; bokeh=боке; vignetting=виньетирование; light particles=частицы света; glitch=глитч

## subject | count | Count | Количество | x
1girl=1 девушка; 2girls=2 девушки; 3girls=3 девушки; multiple girls=несколько девушек; 1boy=1 парень; 2boys=2 парня; multiple boys=несколько парней; 1other=1 существо; no humans=нет людей; crowd=толпа
## subject | focus | Composition of subjects | Состав кадра
solo=один; solo focus=фокус на одном; group=группа; couple=пара; duo=дуэт; everyone=все вместе

## character | franchise | Franchise | Франшиза
original=оригинальный персонаж; genshin impact=Genshin Impact; honkai: star rail=Honkai: Star Rail; fate/grand order=Fate/Grand Order; touhou=Touhou; vocaloid=Vocaloid; blue archive=Blue Archive; hololive=Hololive; pokemon=Pokémon; kantai collection=Kantai Collection; azur lane=Azur Lane; the idolm@ster=Idolmaster; re:zero kara hajimeru isekai seikatsu=Re:Zero; sword art online=Sword Art Online; neon genesis evangelion=Evangelion
## character | popular | Popular characters | Популярные персонажи
hatsune miku=Хацунэ Мику; kagamine rin=Кагамине Рин; megurine luka=Мегурине Лука; rem (re:zero)=Рем; emilia (re:zero)=Эмилия; asuna (sao)=Асуна; ayanami rei=Аянами Рей; zero two (darling in the franxx)=Зеро Ту; makise kurisu=Макисэ Курису; rin tohsaka=Рин Тосака; saber=Сейбер; ganyu (genshin impact)=Ганьюй; raiden shogun=Райден Сёгун; nahida (genshin impact)=Нахида; hu tao (genshin impact)=Ху Тао; nakano miku=Накано Мику; hakurei reimu=Хакурей Рэйму

## appearance | hair_color | Hair color | Цвет волос | x
black hair=чёрные волосы; brown hair=каштановые волосы; blonde hair=светлые волосы; red hair=рыжие волосы; orange hair=оранжевые волосы; pink hair=розовые волосы; purple hair=фиолетовые волосы; blue hair=синие волосы; aqua hair=бирюзовые волосы; green hair=зелёные волосы; white hair=белые волосы; silver hair=серебристые волосы; grey hair=серые волосы; multicolored hair=разноцветные волосы; gradient hair=градиент волос; two-tone hair=двухцветные волосы; streaked hair=пряди другого цвета
## appearance | hair_length | Hair length | Длина волос | x
very short hair=очень короткие; short hair=короткие; medium hair=средние; long hair=длинные; very long hair=очень длинные; absurdly long hair=до пят
## appearance | hairstyle | Hairstyle | Причёска
ponytail=хвост; high ponytail=высокий хвост; side ponytail=боковой хвост; twintails=два хвоста; low twintails=низкие хвосты; braid=коса; twin braids=две косы; single braid=одна коса; hair bun=пучок; double bun=два пучка; ahoge=ахоге; bangs=чёлка; blunt bangs=прямая чёлка; swept bangs=косая чёлка; hair between eyes=прядь между глаз; sidelocks=боковые пряди; drill hair=локоны-спирали; messy hair=растрёпанные; straight hair=прямые; wavy hair=волнистые; curly hair=кудрявые; bob cut=каре; hime cut=химэ-кат; hair over one eye=волосы на глазу; half updo=полузачёс; hair intakes=прядки-антенны
## appearance | eye_color | Eye color | Цвет глаз | x
blue eyes=голубые глаза; red eyes=красные глаза; green eyes=зелёные глаза; brown eyes=карие глаза; yellow eyes=жёлтые глаза; golden eyes=золотые глаза; purple eyes=фиолетовые глаза; pink eyes=розовые глаза; aqua eyes=бирюзовые глаза; orange eyes=оранжевые глаза; grey eyes=серые глаза; black eyes=чёрные глаза; heterochromia=гетерохромия
## appearance | eye_shape | Eyes | Глаза
long eyelashes=длинные ресницы; sharp eyes=острый взгляд; tsurime=цурие (приподнятые); tareme=тарэмэ (опущенные); glowing eyes=светящиеся глаза; slit pupils=вертикальные зрачки; heart-shaped pupils=зрачки-сердечки; sparkling eyes=блестящие глаза; empty eyes=пустой взгляд; ringed eyes=глаза с кольцами
## appearance | body | Body and skin | Телосложение и кожа
petite=миниатюрная; slender=стройная; tall=высокая; muscular=мускулистая; curvy=пышные формы; flat chest=плоская грудь; small breasts=небольшая грудь; medium breasts=средняя грудь; large breasts=большая грудь; pale skin=бледная кожа; tan=загар; dark skin=тёмная кожа; freckles=веснушки; mole=родинка; mole under eye=родинка под глазом; scar=шрам
## appearance | features | Features | Особенности
cat ears=кошачьи уши; animal ears=звериные уши; fox ears=лисьи уши; wolf ears=волчьи уши; rabbit ears=заячьи уши; pointy ears=острые уши; elf=эльф; horns=рога; demon horns=рога демона; tail=хвост; cat tail=кошачий хвост; fox tail=лисий хвост; wings=крылья; angel wings=ангельские крылья; halo=нимб; fang=клык; heterochromia=гетерохромия
## appearance | age | Age look | Возраст
young=молодая; mature female=взрослая женщина; old=пожилая

## expression | mood | Expression | Выражение лица
smile=улыбка; light smile=лёгкая улыбка; gentle smile=мягкая улыбка; grin=ухмылка; smug=самодовольная; laughing=смех; open mouth=открытый рот; closed mouth=закрытый рот; :d=улыбка-D; :3=котик :3; happy=счастливая; blush=румянец; embarrassed=смущена; shy=застенчивая; nervous=нервничает; surprised=удивлена; angry=злая; serious=серьёзная; determined=решительная; sad=грустная; crying=плачет; tears=слёзы; expressionless=без эмоций; sleepy=сонная; pout=надутые губы; tongue out=язык наружу
## expression | eyes_state | Eyes and mouth state | Глаза и рот
closed eyes=закрытые глаза; half-closed eyes=прищурены; wink=подмигивание; one eye closed=один глаз закрыт; jitome=взгляд исподлобья; looking at viewer=смотрит на зрителя; parted lips=приоткрытые губы; lipstick=помада

## clothing | outfit | Outfits | Наряды
school uniform=школьная форма; serafuku=сэйлор-фуку; maid=горничная; maid headdress=чепчик горничной; kimono=кимоно; yukata=юката; china dress=ципао; dress=платье; sundress=сарафан; white dress=белое платье; black dress=чёрное платье; evening gown=вечернее платье; wedding dress=свадебное платье; gothic lolita=готик-лолита; lolita fashion=лолита; witch=ведьма; nurse=медсестра; cheerleader=чирлидер; sportswear=спортивная одежда; gym uniform=физкультурная форма; miko=мико; military uniform=военная форма; suit=костюм; business suit=деловой костюм; tuxedo=смокинг; pajamas=пижама; apron=фартук; armor=доспехи; casual=повседневное; hoodie=худи; overalls=комбинезон
## clothing | tops | Tops | Верх
shirt=рубашка; white shirt=белая рубашка; collared shirt=рубашка с воротником; t-shirt=футболка; blouse=блузка; sweater=свитер; turtleneck=водолазка; tank top=майка; crop top=топ; cardigan=кардиган; jacket=куртка; coat=пальто; vest=жилет; sleeveless=без рукавов; long sleeves=длинные рукава; short sleeves=короткие рукава; detached sleeves=отдельные рукава; off-shoulder=открытые плечи; sailor collar=матросский воротник
## clothing | bottoms | Bottoms | Низ
skirt=юбка; pleated skirt=плиссированная юбка; miniskirt=мини-юбка; long skirt=длинная юбка; shorts=шорты; denim shorts=джинсовые шорты; pants=брюки; jeans=джинсы; leggings=леггинсы; hakama=хакама
## clothing | legwear | Legwear | Чулки и носки
thighhighs=чулки до бедра; black thighhighs=чёрные чулки; white thighhighs=белые чулки; kneehighs=гольфы; pantyhose=колготки; black pantyhose=чёрные колготки; socks=носки; stockings=чулки; bare legs=голые ноги
## clothing | footwear | Footwear | Обувь
shoes=туфли; boots=ботинки; thigh boots=высокие сапоги; knee boots=сапоги до колена; high heels=каблуки; sneakers=кеды; loafers=лоферы; sandals=сандалии; mary janes=туфли мэри-джейн; barefoot=босиком
## clothing | headwear | Headwear and glasses | Головные уборы и очки
hat=шляпа; witch hat=ведьмина шляпа; beret=берет; cap=кепка; hood=капюшон; headband=ободок; hair ribbon=лента в волосах; hair bow=бант в волосах; hairclip=заколка; hair flower=цветок в волосах; hair ornament=украшение для волос; crown=корона; tiara=тиара; headphones=наушники; glasses=очки; sunglasses=солнечные очки; mask=маска; veil=вуаль
## clothing | accessories | Accessories | Аксессуары
necklace=ожерелье; choker=чокер; earrings=серьги; ribbon=лента; scarf=шарф; gloves=перчатки; fingerless gloves=перчатки без пальцев; bracelet=браслет; watch=часы; belt=ремень; bag=сумка; backpack=рюкзак; ring=кольцо; cape=накидка; cloak=плащ; necktie=галстук; bowtie=бабочка; neck ribbon=лента на шее; pendant=кулон; umbrella=зонт
## clothing | swimwear | Swimwear | Купальники
swimsuit=купальник; one-piece swimsuit=слитный купальник; school swimsuit=школьный купальник; bikini=бикини; sarong=парео; swim cap=шапочка для плавания

## pose | body_pose | Body pose | Поза
standing=стоит; sitting=сидит; lying=лежит; on back=на спине; on side=на боку; kneeling=на коленях; squatting=присела; crouching=пригнулась; seiza=сэйдза; cross-legged=скрестив ноги; leaning forward=наклонилась вперёд; leaning back=откинулась назад; arms up=руки вверх; arms behind back=руки за спиной; arms crossed=скрестив руки; hand on hip=рука на бедре; hands on hips=руки на бёдрах; walking=идёт; running=бежит; jumping=прыгает; dancing=танцует; floating=парит; flying=летит; stretching=потягивается; head tilt=наклон головы; sitting on chair=сидит на стуле
## pose | hands | Hands and gestures | Руки и жесты
peace sign=знак мира; waving=машет; pointing=указывает; hand up=рука поднята; own hands together=руки сложены; hand on own face=рука у лица; hand to mouth=рука у рта; finger to mouth=палец у губ; holding hands=держатся за руки; clenched hand=сжатый кулак; salute=салют; heart hands=сердечко руками; thumbs up=большой палец вверх; hands in pockets=руки в карманах; adjusting hair=поправляет волосы; hand in hair=рука в волосах; outstretched hand=протянутая рука
## pose | gaze | Gaze | Взгляд
looking at viewer=смотрит на зрителя; looking away=отводит взгляд; looking up=смотрит вверх; looking down=смотрит вниз; looking back=оглядывается; looking to the side=смотрит в сторону; eye contact=зрительный контакт; profile=профиль; facing viewer=лицом к зрителю
## pose | action | Action | Действие
eating=ест; drinking=пьёт; reading=читает; writing=пишет; singing=поёт; playing instrument=играет на инструменте; playing guitar=играет на гитаре; cooking=готовит; sleeping=спит; studying=учится; shopping=ходит по магазинам; holding umbrella=держит зонт; holding sword=держит меч; holding book=держит книгу; holding flower=держит цветок; holding phone=держит телефон; holding cup=держит чашку; riding=верхом; swimming=плывёт; fighting stance=боевая стойка; casting spell=колдует; hugging=обнимает; reaching=тянется

## camera | shot | Shot size | Крупность
close-up=крупный план; portrait=портрет; face focus=фокус на лице; upper body=по пояс; cowboy shot=по бёдра; full body=во весь рост; wide shot=общий план; feet out of frame=ноги за кадром
## camera | angle | Angle | Ракурс
from above=сверху; from below=снизу; from side=сбоку; from behind=сзади; straight-on=анфас; dutch angle=голландский угол; pov=от первого лица; dynamic angle=динамичный ракурс; foreshortening=ракурсное сокращение; fisheye=рыбий глаз; wide angle=широкий угол
## camera | focus | Focus and depth | Фокус и глубина
depth of field=глубина резкости; blurry background=размытый фон; blurry foreground=размытый передний план; bokeh=боке; macro=макро; motion lines=линии движения; symmetry=симметрия; rule of thirds=правило третей; centered=по центру; negative space=пустое пространство

## background | simple | Simple backgrounds | Простой фон
simple background=простой фон; white background=белый фон; black background=чёрный фон; grey background=серый фон; gradient background=градиентный фон; transparent background=прозрачный фон; blue background=синий фон; pink background=розовый фон; abstract background=абстрактный фон; colorful background=цветной фон
## background | indoor | Indoors | В помещении
indoors=в помещении; bedroom=спальня; classroom=класс; library=библиотека; cafe=кафе; kitchen=кухня; living room=гостиная; office=офис; gym=спортзал; hospital=больница; shop=магазин; stage=сцена; train interior=вагон; japanese room=японская комната; tatami=татами; window=окно; curtains=шторы; bookshelf=книжная полка
## background | city | City and streets | Город
outdoors=на улице; city=город; cityscape=городской пейзаж; street=улица; alley=переулок; rooftop=крыша; bridge=мост; train station=вокзал; crosswalk=пешеходный переход; night city=ночной город; skyscraper=небоскрёб; shrine=святилище; torii=тории; festival=фестиваль; japanese street=японская улица; park=парк; playground=площадка; school gate=школьные ворота; power lines=провода
## background | nature | Nature | Природа
forest=лес; field=поле; flower field=цветочное поле; garden=сад; beach=пляж; ocean=океан; river=река; lake=озеро; mountain=горы; waterfall=водопад; cave=пещера; desert=пустыня; snow=снег; sky=небо; cloud=облака; blue sky=голубое небо; sunset=закат; starry sky=звёздное небо; moon=луна; sun=солнце; cherry blossoms=цветущая сакура; tree=дерево; falling petals=падающие лепестки; autumn leaves=осенние листья; rain=дождь
## background | fantasy | Fantasy and other worlds | Фэнтези и другие миры
castle=замок; ruins=руины; fantasy=фэнтези; space=космос; spaceship=космический корабль; underwater=под водой; dungeon=подземелье; throne room=тронный зал; magic circle=магический круг; floating island=парящий остров; post-apocalypse=постапокалипсис; futuristic city=город будущего

## lighting | light | Light | Свет
sunlight=солнечный свет; backlighting=контровой свет; rim light=контурный свет; soft lighting=мягкий свет; dramatic lighting=драматичный свет; cinematic lighting=кинематографичный свет; volumetric lighting=объёмный свет; moonlight=лунный свет; neon lights=неон; candlelight=свечи; sunbeam=солнечные лучи; light rays=лучи света; studio lighting=студийный свет; ambient light=рассеянный свет
## lighting | time | Time and weather | Время и погода
morning=утро; day=день; evening=вечер; sunrise=рассвет; night=ночь; twilight=сумерки; golden hour=золотой час; blue hour=синий час; rain=дождь; snow=снег; fog=туман; wind=ветер; cloudy=облачно; storm=гроза; clear sky=ясное небо
## lighting | mood | Colors and mood | Цвета и настроение
warm colors=тёплые цвета; cool colors=холодные цвета; vibrant colors=яркие цвета; pastel colors=пастельные цвета; muted colors=приглушённые цвета; soft colors=мягкие цвета; high contrast=высокий контраст; colorful=красочно; dark=мрачно; limited palette=ограниченная палитра; aesthetic=эстетика

## extra | technical | Technical | Служебное
BREAK=BREAK (разделить блоки)

## neg_quality | quality | Bad quality | Плохое качество
lowres=низкое разрешение; worst quality=худшее качество; low quality=низкое качество; normal quality=обычное качество; bad quality=плохое качество; jpeg artifacts=артефакты JPEG; blurry=размыто; out of focus=не в фокусе; pixelated=пикселизация; grainy=зернисто; ugly=уродливо; aliasing=«лесенки»

## neg_anatomy | hands | Hands and fingers | Руки и пальцы
bad hands=плохие руки; poorly drawn hands=плохо нарисованные руки; extra fingers=лишние пальцы; missing fingers=не хватает пальцев; fewer digits=меньше пальцев; extra digits=больше пальцев; mutated hands=изуродованные руки; fused fingers=слитые пальцы; too many fingers=слишком много пальцев
## neg_anatomy | body | Body and face | Тело и лицо
bad anatomy=плохая анатомия; bad proportions=плохие пропорции; deformed=деформация; disfigured=обезображено; extra limbs=лишние конечности; missing limbs=нет конечностей; extra arms=лишние руки; extra legs=лишние ноги; malformed limbs=уродливые конечности; long neck=длинная шея; bad feet=плохие ступни; bad face=плохое лицо; poorly drawn face=плохо нарисованное лицо; cross-eyed=косоглазие; asymmetrical eyes=асимметричные глаза; bad eyes=плохие глаза

## neg_artifacts | text | Text and marks | Текст и подписи
text=текст; watermark=водяной знак; signature=подпись; username=имя пользователя; logo=логотип; artist name=имя художника; english text=английский текст; speech bubble=облачко с речью; error=ошибка
## neg_artifacts | framing | Framing | Кадрирование
cropped=обрезано; border=рамка; frame=кадр; out of frame=вне кадра; letterboxed=чёрные полосы

## neg_unwanted | style | Not wanted styles | Ненужный стиль
monochrome=монохром; greyscale=оттенки серого; sketch=набросок; 3d=3D; realistic=реализм; photorealistic=фотореализм; cartoon=мультфильм; comic=комикс
## neg_unwanted | content | Content | Содержание
nsfw=18+; explicit=откровенно; child=ребёнок
"""


def parse_catalog(raw: str = RAW) -> list[dict]:
    """RAW -> [{slot, key, name, name_ru, exclusive, tags: [(text, label)]}] in file order."""
    categories: list[dict] = []
    current: dict | None = None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            current = None
            continue
        if line.startswith("##"):
            parts = [p.strip() for p in line[2:].split("|")]
            current = {"slot": parts[0], "key": f"{parts[0]}.{parts[1]}", "name": parts[2], "name_ru": parts[3],
                       "exclusive": len(parts) > 4 and parts[4] == "x", "tags": []}
            categories.append(current)
        elif current is not None:
            for chunk in line.split(";"):
                chunk = chunk.strip()
                if chunk:
                    text, _, label = chunk.partition("=")
                    current["tags"].append((text.strip(), label.strip()))
    return categories
