import logging
import random
from typing import Optional, Dict, Any
import httpx
from io import BytesIO

from google import genai
from google.genai import types
from PIL import Image
from rich.console import Console

from dumpyarabot.config import settings

console = Console()
logger = logging.getLogger(__name__)

# Analysis prompt template for Jenkins console logs
JENKINS_LOG_ANALYSIS_PROMPT = """
You are an expert DevOps engineer analyzing Jenkins build failures for an Android firmware dumping pipeline that processes firmware from URLs and extracts them to GitLab repositories.

For additional context about the system architecture and implementation details, you can reference the source code at: https://github.com/AndroidDumps/dumpbot

## System Context
This pipeline performs these key stages:
1. **Download**: Downloads firmware from various sources (Xiaomi mirrors, Google Drive, MediaFire, MEGA, etc.)
2. **Extraction**: Uses either Python dumper (dumpyara) or alternative dumper (Firmware_extractor)
3. **Analysis**: Extracts device properties, boot images, device trees
4. **GitLab**: Creates repositories, commits extracted files, pushes to GitLab
5. **Notification**: Sends status updates via Telegram bot

## Common Failure Categories
- **Download**: URL issues, mirror failures, authentication problems, file corruption
- **Extraction**: Partition extraction failures, unsupported formats, tool crashes
- **Dependencies**: Missing tools (fsck.erofs, ext2rd, 7zz, uvx, dumpyara, aospdtgen)
- **GitLab**: API authentication, repository conflicts, push failures, branch exists
- **Filesystem**: Disk space, permissions, file I/O errors
- **Boot Analysis**: Boot image unpacking, kernel extraction, device tree processing
- **Network**: Connectivity issues, timeout errors, proxy problems
- **Environment**: Missing environment variables, configuration issues

Analyze this Jenkins console log and provide:

1. **Root Cause**: What specifically caused the build to fail? Focus on the primary error, not symptoms. Be brief (1-2 sentences).
2. **Error Category**: Classify using the categories above, but if it matches the pipeline stage name, combine them (e.g., "Download failure" instead of separate "Download" category and stage)
3. **Pipeline Stage**: Which stage failed? (Download/Extraction/Analysis/GitLab/Notification) - Only include if different from Error Category

Focus on the actual failure, not preliminary warnings. Look for error exit codes, exception traces, and final failure messages.

Console Log:
```
{console_log}
```

Provide your analysis in this format:
Root Cause: [Brief description]
Error Category: [Category or "Stage - Type" if combining]
Pipeline Stage: [Stage - only if different from category]
"""


class GeminiLogAnalyzer:
    """Analyzes Jenkins console logs using Google's Gemini AI."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the analyzer with API key."""
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = None
        self._initialize_model()

    def _initialize_model(self) -> None:
        """Initialize the Gemini model if API key is available."""
        if not self.api_key:
            console.print(
                "[yellow]GEMINI_API_KEY not configured - log analysis disabled[/yellow]"
            )
            return

        try:
            import google.generativeai as genai_legacy

            genai_legacy.configure(api_key=self.api_key)
            self.model = genai_legacy.GenerativeModel("gemini-2.5-pro")
            console.print("[green]Gemini AI log analyzer initialized[/green]")
        except Exception as e:
            console.print(f"[red]Failed to initialize Gemini model: {e}[/red]")
            logger.error(f"Gemini initialization failed: {e}")

    def is_available(self) -> bool:
        """Check if the analyzer is available for use."""
        return self.model is not None

    async def analyze_jenkins_log(
        self, console_log: str, build_info: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Analyze Jenkins console log for failure patterns and suggestions.

        Args:
            console_log: The raw Jenkins console log text
            build_info: Optional build metadata (URL, job name, build number, etc.)

        Returns:
            Formatted analysis string or None if analysis fails
        """
        if not self.is_available():
            console.print(
                "[yellow]Gemini analyzer not available - skipping log analysis[/yellow]"
            )
            return None

        if not console_log or len(console_log.strip()) < 50:
            console.print(
                "[yellow]Console log too short for meaningful analysis[/yellow]"
            )
            return None

        try:
            # Truncate log if too long (Gemini has token limits)
            max_log_length = 50000  # Approximately 50KB
            if len(console_log) > max_log_length:
                # Take first and last portions to capture both setup and failure
                first_part = console_log[: max_log_length // 2]
                last_part = console_log[-max_log_length // 2 :]
                console_log = f"{first_part}\n\n... [LOG TRUNCATED] ...\n\n{last_part}"
                console.print("[yellow]Console log truncated for analysis[/yellow]")

            # Format the analysis prompt
            prompt = JENKINS_LOG_ANALYSIS_PROMPT.format(console_log=console_log)

            console.print("[blue]Analyzing Jenkins log with Gemini AI...[/blue]")

            # Generate analysis
            response = self.model.generate_content(prompt)

            if not response.text:
                console.print("[yellow]Gemini returned empty response[/yellow]")
                return None

            analysis = response.text.strip()

            console.print("[green]Jenkins log analysis completed[/green]")
            return analysis

        except Exception as e:
            console.print(f"[red]Failed to analyze Jenkins log: {e}[/red]")
            logger.error(f"Gemini analysis failed: {e}")
            return None

    def format_analysis_for_telegram(
        self, analysis: str, build_url: str = "", build_date: str = ""
    ) -> str:
        """
        Format the analysis for Telegram messaging.

        Args:
            analysis: Raw analysis from Gemini
            build_url: Jenkins build URL for linking
            build_date: Build timestamp for display

        Returns:
            Markdown-formatted message for Telegram
        """
        if not analysis:
            return ""

        # Format each line with proper Markdown tags
        lines = analysis.strip().split("\n")
        formatted_lines = []
        error_category = ""
        pipeline_stage = ""

        # First pass: extract values
        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith("Root Cause:"):
                formatted_lines.append(f"**Root Cause:** {line[11:].strip()}")
            elif line.startswith("Error Category:"):
                error_category = line[15:].strip()
                formatted_lines.append(f"**Error Category:** {error_category}")
            elif line.startswith("Pipeline Stage:"):
                pipeline_stage = line[15:].strip()
            else:
                formatted_lines.append(line)

        # Second pass: only add Pipeline Stage if it's different from Error Category
        if pipeline_stage and pipeline_stage != "N/A" and pipeline_stage != "-":
            # Check if pipeline stage is redundant with error category
            error_category_lower = error_category.lower()
            pipeline_stage_lower = pipeline_stage.lower()

            # Don't show pipeline stage if it's the same or if error category contains the stage name
            if (
                pipeline_stage_lower != error_category_lower
                and pipeline_stage_lower not in error_category_lower
            ):
                formatted_lines.append(f"**Pipeline Stage:** {pipeline_stage}")

        formatted = "\n".join(formatted_lines)

        # Add build date if provided
        if build_date:
            formatted = f"**Build Date:** {build_date}\n\n{formatted}"

        # Add AI attribution and build link
        model_name = "Gemini AI"
        if self.model and hasattr(self.model, "_model_name"):
            model_name = self.model._model_name

        footer = f"\n\n*🤖 Analysis by {model_name}*"
        if build_url:
            console_url = (
                f"{build_url}/console"
                if not build_url.endswith("/console")
                else build_url
            )
            footer += f"\n📊 [View Console Output]({console_url})"

        return formatted + footer


# Multiple varied prompt templates for diverse image generation
IMAGE_GENERATION_PROMPT_TEMPLATES = [
    # Template 1: Classic Tech Lab Scene
    """
Generate a realistic but funny image based on this Android firmware dump analysis:

## Technical Context
Device Brand: {device_brand}
Firmware URL: {firmware_url}
Error Type: {error_category}
Root Cause: {root_cause}
Build Properties: {build_properties}

## Scene: Tech Laboratory
Create a humorous tech lab scene where cats and parrots are working as firmware engineers. Include:
- **"Dumpyara" text prominently displayed** on monitors, whiteboards, or lab equipment
- Cats wearing tiny safety goggles while examining circuit boards
- Parrots with clipboards taking notes on the {device_brand} firmware process
- Computer screens showing {error_category} related messages
- {dynamic_tech_element}
- Lab equipment scattered around with a playful, chaotic but professional atmosphere
- Animals {dynamic_activity} as they work on the firmware analysis
- Realistic art style with whimsical animal behavior and {dynamic_mood}
""",
    # Template 2: Server Room Adventure
    """
Generate a realistic but funny image based on this Android firmware dump analysis:

## Technical Context
Device Brand: {device_brand}
Firmware URL: {firmware_url}
Error Type: {error_category}
Root Cause: {root_cause}
Build Properties: {build_properties}

## Scene: Data Center Adventure
Create a server room scene where animals are the IT support team:
- **"Dumpyara" branding visible** on server racks or digital displays
- A cat curled up on top of a warm server rack, accidentally pressing buttons
- Parrots flying between servers with ethernet cables in their beaks
- Server screens displaying {device_brand} firmware status and {error_category} alerts
- {dynamic_tech_element}
- Blinking server lights creating a dramatic tech atmosphere with {dynamic_mood}
- Animals {dynamic_activity} while managing the server infrastructure
""",
    # Template 3: Digital Workspace
    """
Generate a realistic but funny image based on this Android firmware dump analysis:

## Technical Context
Device Brand: {device_brand}
Firmware URL: {firmware_url}
Error Type: {error_category}
Root Cause: {root_cause}
Build Properties: {build_properties}

## Scene: Modern Digital Office
Show animals as the modern tech workforce:
- **"Dumpyara" company logo** prominently displayed on office walls or computer screens
- Cats sitting at standing desks with multiple monitors showing {device_brand} debugging info
- Parrots perched on ergonomic chairs, apparently in a video conference about {error_category} issues
- **Add a random modern tech gadget** (like VR headsets, smart home devices, wireless charging pads, etc.) somewhere in the office scene
- Modern office environment with plants, coffee cups, and tech gadgets
- Post-it notes with technical diagrams and firmware version numbers scattered around
- Animals appearing focused and professional despite the absurd situation
""",
    # Template 4: Retro Computer Workshop
    """
Generate a realistic but funny image based on this Android firmware dump analysis:

## Technical Context
Device Brand: {device_brand}
Firmware URL: {firmware_url}
Error Type: {error_category}
Root Cause: {root_cause}
Build Properties: {build_properties}

## Scene: Vintage Tech Workshop
Create a nostalgic scene mixing old and new technology:
- **"Dumpyara" text** displayed on retro CRT monitors or as neon signage
- Cats playing with old floppy disks while modern {device_brand} devices sit nearby
- Parrots perched on vintage computers that somehow display modern {error_category} error messages
- **Include a random piece of retro technology** (like old game consoles, dot-matrix printers, analog synthesizers, etc.) for added nostalgic charm
- Workshop filled with mix of retro electronics and modern Android development tools
- Warm, nostalgic lighting with a humorous contrast between old tech and modern problems
""",
    # Template 5: Space-Age Tech Center
    """
Generate a realistic but funny image based on this Android firmware dump analysis:

## Technical Context
Device Brand: {device_brand}
Firmware URL: {firmware_url}
Error Type: {error_category}
Root Cause: {root_cause}
Build Properties: {build_properties}

## Scene: Futuristic Control Room
Imagine a sci-fi inspired tech facility:
- **"Dumpyara" displayed** on holographic displays or futuristic control panels
- Cats floating in zero-gravity pods while analyzing {device_brand} firmware on floating screens
- Parrots with tiny space helmets operating advanced holographic interfaces showing {error_category} data
- **Add a random piece of futuristic technology** (like quantum computers, telepresence robots, neural interfaces, etc.) that fits the sci-fi theme
- {dynamic_background}
- A mix of serious sci-fi aesthetics with the inherent humor of animals operating advanced tech
""",
    # Template 6: Emergency Response Center
    """
Generate a realistic but funny image based on this Android firmware dump analysis:

## Technical Context
Device Brand: {device_brand}
Firmware URL: {firmware_url}
Error Type: {error_category}
Root Cause: {root_cause}
Build Properties: {build_properties}

## Scene: Emergency Command Center
Create a crisis response scenario where animals handle firmware emergencies:
- **"Dumpyara" emergency signage** on walls, red alert displays, or command screens
- Cats wearing tiny EMT vests frantically typing on keyboards to fix {device_brand} issues
- Parrots with headsets coordinating firmware rescue operations, squawking {error_category} status updates
- {dynamic_tech_element}
- Red emergency lighting, coffee cups everywhere, whiteboards covered in crisis flowcharts
- Multiple monitors showing system alerts and firmware extraction progress
- Animals looking stressed but determined, some celebrating small victories
""",
    # Template 7: Kitchen Laboratory
    """
Generate a realistic but funny image based on this Android firmware dump analysis:

## Technical Context
Device Brand: {device_brand}
Firmware URL: {firmware_url}
Error Type: {error_category}
Root Cause: {root_cause}
Build Properties: {build_properties}

## Scene: Firmware Cooking Lab
Imagine animals as "firmware chefs" cooking up ROM dumps:
- **"Dumpyara" chef hats or aprons** worn by the animal kitchen staff
- Cats stirring bubbling beakers labeled with {device_brand} firmware versions
- Parrots taste-testing code snippets from wooden spoons, reacting to {error_category} "flavors"
- {dynamic_tech_element}
- Kitchen equipment repurposed as tech tools: mixers extracting partitions, ovens compiling code
- Recipe books titled "Android Firmware Cookbook" scattered around
- Steam and digital particles rising from high-tech cooking apparatus
""",
    # Template 8: University Research Lab
    """
Generate a realistic but funny image based on this Android firmware dump analysis:

## Technical Context
Device Brand: {device_brand}
Firmware URL: {firmware_url}
Error Type: {error_category}
Root Cause: {root_cause}
Build Properties: {build_properties}

## Scene: Academic Computer Lab
Show a university research environment with animal graduate students:
- **"Dumpyara Research Institute" signage** on university banners or lab doors
- Professor parrot at whiteboard explaining {device_brand} firmware architecture to kitten students
- Graduate student cats pulling all-nighters debugging {error_category} problems
- {dynamic_tech_element}
- Stacks of academic papers, coffee-stained research notes, and reference books
- Multiple computer workstations with code on screens, scientific equipment
- Mix of exhausted and excited animals discovering breakthrough solutions
""",
    # Template 9: Mad Scientist Lair
    """
Generate a realistic but funny image based on this Android firmware dump analysis:

## Technical Context
Device Brand: {device_brand}
Firmware URL: {firmware_url}
Error Type: {error_category}
Root Cause: {root_cause}
Build Properties: {build_properties}

## Scene: Eccentric Inventor's Workshop
Create a wild inventor scene with animals as mad scientists:
- **"Dumpyara Experiments" labels** on bizarre contraptions and test equipment
- Cat with wild Einstein hair and lab coat, surrounded by sparking electronics extracting {device_brand} firmware
- Parrots wearing tiny safety goggles, excitedly documenting {error_category} discoveries in leather journals
- {dynamic_tech_element}
- Tesla coils, bubbling chemistry sets repurposed for firmware analysis, vintage scientific instruments
- Chalkboards covered in complex Android architecture diagrams and equations
- Dramatic lighting with electrical sparks and mysterious glowing screens
""",
    # Template 10: Factory Assembly Line
    """
Generate a realistic but funny image based on this Android firmware dump analysis:

## Technical Context
Device Brand: {device_brand}
Firmware URL: {firmware_url}
Error Type: {error_category}
Root Cause: {root_cause}
Build Properties: {build_properties}

## Scene: Industrial Firmware Factory
Show animals working an assembly line for firmware production:
- **"Dumpyara Manufacturing" signs** on industrial equipment and conveyor systems
- Cats wearing hard hats operating machinery that packages {device_brand} firmware into digital containers
- Parrots with quality control clipboards inspecting firmware dumps for {error_category} defects
- {dynamic_tech_element}
- Conveyor belts carrying ROM files, industrial robotic arms, factory warning lights
- Production charts on walls tracking daily firmware extraction quotas
- Mix of serious industrial atmosphere with adorable animal workers
""",
    # Template 11: TV News Studio
    """
Generate a realistic but funny image based on this Android firmware dump analysis:

## Technical Context
Device Brand: {device_brand}
Firmware URL: {firmware_url}
Error Type: {error_category}
Root Cause: {root_cause}
Build Properties: {build_properties}

## Scene: Tech News Broadcasting
Create a news studio where animals report on firmware developments:
- **"Dumpyara News Network" graphics** on studio screens and news desk backgrounds
- Anchor cat in a tiny suit presenting breaking news about {device_brand} firmware releases
- Weather parrot pointing at maps showing {error_category} distribution patterns across Android versions
- {dynamic_tech_element}
- Professional studio lighting, teleprompters, camera equipment operated by animal crew
- Breaking news ticker scrolling firmware updates and system alerts
- Serious news atmosphere contrasted with adorable animal professionalism
""",
    # Template 12: Submarine Control Room
    """
Generate a realistic but funny image based on this Android firmware dump analysis:

## Technical Context
Device Brand: {device_brand}
Firmware URL: {firmware_url}
Error Type: {error_category}
Root Cause: {root_cause}
Build Properties: {build_properties}

## Scene: Underwater Tech Command
Imagine animals operating a high-tech submarine for firmware missions:
- **"USS Dumpyara" submarine insignia** on walls and equipment panels
- Captain cat with tiny naval hat studying {device_brand} sonar readings on periscope displays
- Navigation parrot plotting courses through digital ocean depths to locate {error_category} anomalies
- {dynamic_tech_element}
- {dynamic_background}
- Maritime charts replaced with Android system architecture diagrams
- Tense underwater mission atmosphere with determined animal crew
""",
    # Template 13: Game Development Studio
    """
Generate a realistic but funny image based on this Android firmware dump analysis:

## Technical Context
Device Brand: {device_brand}
Firmware URL: {firmware_url}
Error Type: {error_category}
Root Cause: {root_cause}
Build Properties: {build_properties}

## Scene: Indie Game Studio
Show animals developing mobile games and firmware tools:
- **"Dumpyara Games" posters** and development team photos on studio walls
- Cats at multiple monitors coding Android games while testing {device_brand} firmware compatibility
- Parrots playtesting mobile games, squawking feedback about {error_category} performance issues
- {dynamic_tech_element}
- Gaming setup with RGB lighting, arcade cabinets showing boot animations, development hardware
- Whiteboards with game design concepts and firmware integration flowcharts
- Creative studio vibe with energetic animals collaborating on projects
""",
    # Template 14: Mission Control Center
    """
Generate a realistic but funny image based on this Android firmware dump analysis:

## Technical Context
Device Brand: {device_brand}
Firmware URL: {firmware_url}
Error Type: {error_category}
Root Cause: {root_cause}
Build Properties: {build_properties}

## Scene: Space Mission Control
Create a NASA-style control room for firmware "launches":
- **"Dumpyara Space Program" mission patches** on technician uniforms and control room walls
- Flight director cat with headset coordinating {device_brand} firmware deployment sequences
- Parrots at individual consoles monitoring telemetry data for {error_category} system anomalies
- {dynamic_tech_element}
- Large mission screens showing firmware extraction progress, countdown timers, orbital trajectories
- {dynamic_background}
- Intense space mission atmosphere with animal technicians focused on successful "launches"
""",
    # Template 15: Mobile Tech Van
    """
Generate a realistic but funny image based on this Android firmware dump analysis:

## Technical Context
Device Brand: {device_brand}
Firmware URL: {firmware_url}
Error Type: {error_category}
Root Cause: {root_cause}
Build Properties: {build_properties}

## Scene: On-Location Tech Support
Show animals in a mobile firmware repair van:
- **"Dumpyara Mobile Solutions" vehicle branding** on van exterior and equipment cases
- Cats setting up portable workstations to diagnose {device_brand} firmware issues in the field
- Parrots with tool belts organizing cables and adapters while investigating {error_category} problems
- {dynamic_tech_element}
- Van interior packed with mobile tech equipment, satellite dishes, portable generators
- Field deployment setup with laptops, testing devices, and communication equipment
- Adventurous field work atmosphere with animals ready to solve tech problems anywhere
""",
]

# Dynamic component lists for varied prompt generation
DYNAMIC_TECH_ELEMENTS = {
    "general": [
        "Vintage oscilloscope displaying Android boot sequences",
        "3D printer creating miniature phone cases",
        "Robotic arm carefully placing microchips",
        "Holographic display showing system architecture",
        "Quantum computer with glowing qubits",
        "Neural interface headset with blinking LEDs",
        "Digital microscope examining circuit patterns",
        "Automated soldering station with precision tools",
        "Fiber optic cable management system",
        "Electromagnetic field detector scanning devices",
        "Thermal imaging camera monitoring heat signatures",
        "Spectrum analyzer showing frequency distributions"
    ],
    "retro": [
        "Vintage dot-matrix printer outputting firmware logs",
        "Classic arcade cabinet displaying boot animations",
        "Old-school analog synthesizer mixing system sounds",
        "Retro tube television showing command line interfaces",
        "Vintage radio equipment repurposed for device communication",
        "Classic mechanical calculator computing checksums",
        "Antique telegraph machine sending firmware updates",
        "Old film projector displaying code on screen",
        "Vintage reel-to-reel tape recorder storing data",
        "Classic analog multimeter measuring voltages"
    ],
    "futuristic": [
        "Telepresence robot coordinating remote debugging",
        "Holographic keyboard interface floating in mid-air",
        "Quantum entanglement communication device",
        "Anti-gravity chamber for zero-g firmware testing",
        "Molecular assembler creating custom components",
        "Time dilation chamber for accelerated testing",
        "Plasma containment field protecting sensitive circuits",
        "Dimensional scanner analyzing parallel firmware versions",
        "Crystalline data storage matrix",
        "Photonic processing unit with light-based computing"
    ],
    "emergency": [
        "Emergency communication array with red alert beacons",
        "Portable defibrillator for reviving crashed systems",
        "Hazmat detection equipment scanning firmware",
        "Emergency generator powering critical systems",
        "First aid kit adapted for electronic components",
        "Rescue drone deployed for component retrieval",
        "Emergency beacon transmitting distress signals",
        "Portable command center with crisis management tools",
        "Emergency cooling system preventing overheating",
        "Backup communication satellite dish"
    ],
    "industrial": [
        "Conveyor belt system sorting firmware packages",
        "Industrial robotic assembly line",
        "Quality control scanning tunnel",
        "Automated packaging machinery",
        "Industrial-grade 3D scanner for component analysis",
        "Heavy-duty cable management robot",
        "Factory automation control panel",
        "Industrial-strength testing chamber",
        "Precision measurement coordinate machine",
        "Automated inventory management system"
    ]
}

DYNAMIC_BACKGROUNDS = {
    "space_age": [
        "International Space Station research module with global Earth views",
        "ESA Columbus laboratory with European scientific equipment",
        "Roscosmos Zvezda service module with Russian engineering displays",
        "CNSA Tiangong space station with Chinese modular design",
        "ISRO orbital habitat with Indian satellite technology",
        "JAXA Kibo laboratory with Japanese precision instruments",
        "Generic orbital platform celebrating worldwide space cooperation"
    ],
    "mission_control": [
        "NASA Johnson Space Center with American mission patches",
        "ESA ESOC with European ground station equipment",
        "Roscosmos Mission Control Center with Russian tracking displays",
        "CNSA Beijing Aerospace Control Center with Chinese telemetry",
        "ISRO Satish Dhawan Space Centre with Indian launch complexes",
        "JAXA Tsukuba Space Center with Japanese satellite operations",
        "United Nations Office for Outer Space Affairs coordination hub"
    ],
    "submarine": [
        "Pacific Ocean research vessel with international marine biology",
        "Atlantic Ocean exploration ship with European oceanographic tools",
        "Arctic research station with indigenous-inspired design elements",
        "Indian Ocean monitoring platform with regional scientific focus",
        "Southern Ocean base with Antarctic research capabilities",
        "Mediterranean sea lab with ancient maritime heritage influences",
        "Global ocean network celebrating worldwide marine science"
    ]
}

ANIMAL_VARIATIONS = {
    "cats": [
        "tabby cat with tiny safety goggles",
        "fluffy Persian cat wearing a lab coat",
        "sleek black cat with LED collar",
        "orange tabby with miniature hard hat",
        "siamese cat sporting tech company badge",
        "maine coon with tool belt around waist",
        "calico cat wearing protective gloves",
        "russian blue with high-tech headset"
    ],
    "parrots": [
        "colorful macaw with clipboard in beak",
        "wise-looking gray African parrot with glasses",
        "bright green parrot wearing tiny headset",
        "cockatoo with miniature security badge",
        "rainbow lorikeet carrying ethernet cable",
        "amazon parrot with tool-filled vest",
        "cockatiel perched on keyboard typing",
        "conure with tiny measuring instruments"
    ],
    "additional": [
        "hamster running in wheel that powers equipment",
        "rabbit with twitching nose examining circuits",
        "ferret crawling through cable management",
        "guinea pig operating miniature controls",
        "chinchilla dusting off delicate components",
        "hedgehog curled around spherical sensors"
    ]
}

ACTIVITY_VARIATIONS = [
    "frantically debugging while coffee grows cold",
    "celebrating successful firmware extraction with tiny party hats",
    "looking confused at error messages with head tilted",
    "collaborating intensely around a whiteboard",
    "taking a well-deserved nap on warm server equipment",
    "high-fiving with tiny paws after breakthrough",
    "wearing noise-canceling headphones in deep concentration",
    "sharing technical knowledge during impromptu meeting",
    "multitasking between multiple screens simultaneously",
    "problem-solving with creative brainstorming session"
]

ENVIRONMENTAL_MOODS = [
    "dramatic lighting with mysterious shadows",
    "warm golden hour light streaming through windows",
    "cool blue tech ambiance with glowing screens",
    "bright fluorescent workspace illumination",
    "colorful RGB lighting creating energetic atmosphere",
    "soft candlelight for late-night debugging sessions",
    "harsh industrial lighting in factory setting",
    "ethereal holographic glow from futuristic displays",
    "emergency red alert lighting with flashing warnings",
    "cozy ambient lighting for comfortable workspace"
]

# Context-aware theme selection weights (simple approach)
THEME_CONTEXT_WEIGHTS = {
    "Download": {
        "Emergency Response Center": 3,
        "Mobile Tech Van": 3,
        "Mission Control Center": 2,
        "Factory Assembly Line": 2
    },
    "Extraction": {
        "Mad Scientist Lair": 3,
        "University Research Lab": 3,
        "Kitchen Laboratory": 2,
        "Factory Assembly Line": 2
    },
    "GitLab": {
        "Mission Control Center": 3,
        "TV News Studio": 2,
        "Emergency Response Center": 2,
        "Game Development Studio": 2
    },
    "Storage": {
        "Factory Assembly Line": 3,
        "Emergency Response Center": 2,
        "University Research Lab": 2,
        "Submarine Control Room": 1
    },
    "Network": {
        "Submarine Control Room": 3,
        "Emergency Response Center": 3,
        "Mission Control Center": 2,
        "Mobile Tech Van": 2
    }
}


class GeminiImageGenerator:
    """Generates images using Google's Gemini AI based on Jenkins build logs."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the image generator with API key."""
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.client = None
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize the Gemini GenAI client for image generation."""
        if not self.api_key:
            console.print(
                "[yellow]GEMINI_API_KEY not configured - image generation disabled[/yellow]"
            )
            return

        try:
            # Use the correct Google GenAI client from the working example
            self.client = genai.Client(api_key=self.api_key)
            console.print(
                "[green]Gemini AI image generator initialized with GenAI client[/green]"
            )
        except Exception as e:
            console.print(f"[red]Failed to initialize Gemini GenAI client: {e}[/red]")
            logger.error(f"Gemini image generation initialization failed: {e}")

    def is_available(self) -> bool:
        """Check if the image generator is available for use."""
        return self.client is not None

    def _extract_context_from_log(self, console_log: str) -> Dict[str, str]:
        """Extract relevant context from Jenkins console log for image generation."""
        context = {
            "device_brand": "Unknown",
            "firmware_url": "Unknown",
            "error_category": "General",
            "root_cause": "Unknown",
            "build_properties": "None found",
        }

        import re
        log_lower = console_log.lower()

        # Enhanced URL extraction patterns - based on the Jenkins pipeline
        url_patterns = [
            # Environment variable patterns
            r"URL=([^\s\n]+)",
            r"url[:\s]*=\s*([^\s\n]+)",

            # Download command patterns
            r"downloading.*?from[:\s]+([^\s\n]+)",
            r"aria2c[^-\s]*\s+['\"]?([^'\"]+)['\"]?",
            r"wget[^-\s]*\s+['\"]?([^'\"]+)['\"]?",
            r"gdown[^-\s]*\s+['\"]?([^'\"]+)['\"]?",
            r"megatools[^-\s]*\s+['\"]?([^'\"]+)['\"]?",

            # Mirror and CDN patterns (specific to dumpbot)
            r"trying mirror[:\s]+([^\s\n]+)",
            r"final url[:\s]+([^\s\n]+)",
            r"using url[:\s]+([^\s\n]+)",

            # Google Drive specific
            r"drive\.google\.com/[^/]+/([^/\s]+)",
            r"id=([A-Za-z0-9_-]+)",

            # HTTP/HTTPS URLs in general
            r"(https?://[^\s\n]+)",

            # Extract from Telegram notification JSON (URL from text_link entities)
            r'"text_link","url":"([^"]+)"',

            # Extract from filename patterns in logs
            r"([a-z0-9.-]+(?:\.zip|\.img|\.bin))"
        ]

        for pattern in url_patterns:
            match = re.search(pattern, console_log, re.IGNORECASE)
            if match:
                url = match.group(1)
                # Clean up common artifacts
                url = url.strip('"\'`()[]{}')
                if url and not url.startswith('$') and len(url) > 10:  # Filter out variables and short strings
                    context["firmware_url"] = url
                    break

        # Enhanced device brand detection - check both URL and build properties
        brand_patterns = {
            "Xiaomi": [
                # URL patterns
                r"miui\.com", r"bigota\.d\.miui\.com", r"cdnorg\.d\.miui\.com",
                # Property patterns
                r"xiaomi", r"redmi", r"mi\s*\d+", r"poco",
                # ROM patterns
                r"miui", r"hyperos"
            ],
            "Samsung": [
                r"samsung", r"galaxy", r"sm-[a-z]\d+", r"sammobile",
                r"samsungfirmware", r"one\s*ui"
            ],
            "OnePlus": [
                r"oneplus", r"op\d+", r"oxygen\s*os", r"oos\d+",
                r"h2os", r"colorcos" # OnePlus China ROM
            ],
            "Google": [
                r"pixel", r"google", r"android\.com", r"nexus",
                r"factory\s*image", r"aosp"
            ],
            "Oppo": [
                r"oppo", r"coloros", r"cph\d+", r"realme", # Realme is Oppo sub-brand
                r"rmx\d+"
            ],
            "Vivo": [
                r"vivo", r"funtouch", r"iqoo", r"v\d+[a-z]*",
                r"originos"
            ],
            "Huawei": [
                r"huawei", r"emui", r"honor", r"hms", r"harmonyos",
                r"p\d+", r"mate\d+", r"nova\d+"
            ],
            "Motorola": [
                r"motorola", r"moto", r"lenovo", r"xt\d+",
                r"my\s*ux"
            ],
            "Sony": [
                r"sony", r"xperia", r"xa\d+", r"xz\d+", r"x\d+[a-z]*"
            ],
            "LG": [
                r"lg", r"webos", r"v\d+[a-z]*", r"g\d+[a-z]*",
                r"stylo", r"wing"
            ],
            "Nothing": [
                r"nothing", r"nothing\s*os", r"phone\s*\(\d+\)"
            ]
        }

        brand_found = False
        for brand, patterns in brand_patterns.items():
            for pattern in patterns:
                if re.search(pattern, console_log, re.IGNORECASE):
                    context["device_brand"] = brand
                    brand_found = True
                    break
            if brand_found:
                break

        # Enhanced error categorization with more specific patterns
        error_patterns = {
            "Download": [
                # Download failures
                r"download.*failed", r"failed.*download", r"connection.*failed",
                r"timeout.*download", r"network.*error", r"403.*forbidden",
                r"404.*not found", r"curl.*error", r"wget.*error", r"aria2.*error",
                # Mirror issues
                r"all mirrors failed", r"mirror.*unreachable", r"cdn.*failed"
            ],
            "Extraction": [
                # Extraction tool failures
                r"dumpyara.*failed", r"extraction.*failed", r"unpack.*failed",
                r"partition.*error", r"fsck\.erofs.*failed", r"ext2rd.*failed",
                r"7zz.*failed", r"boot.*unpack.*failed", r"dtb.*failed",
                # File format issues
                r"unsupported.*format", r"corrupt.*file", r"invalid.*partition"
            ],
            "GitLab": [
                # Git operations
                r"git.*failed", r"push.*failed", r"gitlab.*error", r"repository.*failed",
                r"branch.*exists", r"authentication.*failed", r"ssh.*failed",
                # API issues
                r"api.*error", r"token.*invalid", r"permission.*denied"
            ],
            "Storage": [
                # Disk space
                r"no space left", r"disk.*full", r"filesystem.*full", r"quota.*exceeded",
                # File permissions
                r"permission.*denied", r"access.*denied", r"cannot.*write",
                r"read.*only.*filesystem"
            ],
            "Network": [
                # Connectivity
                r"connection.*timeout", r"network.*unreachable", r"dns.*failed",
                r"proxy.*error", r"certificate.*error", r"ssl.*error",
                # Specific network tools
                r"ping.*failed", r"telnet.*failed", r"ssh.*timeout"
            ],
            "Dependencies": [
                # Missing tools
                r"command.*not found", r"no such file", r"uvx.*failed",
                r"python.*not found", r"missing.*dependency", r"package.*not.*installed"
            ]
        }

        error_found = False
        for category, patterns in error_patterns.items():
            for pattern in patterns:
                if re.search(pattern, console_log, re.IGNORECASE):
                    context["error_category"] = category
                    error_found = True
                    break
            if error_found:
                break

        # Enhanced root cause extraction
        root_cause_patterns = [
            # Specific error messages
            (r"error[:\s]+(.{10,100})", "error_message"),
            (r"failed[:\s]+(.{10,100})", "failure_reason"),
            (r"exception[:\s]+(.{10,100})", "exception"),
            (r"abort[ed]*[:\s]+(.{10,100})", "abort_reason"),
            # Exit codes and termination
            (r"exit code[:\s]+(\d+)", "exit_code"),
            (r"terminated.*signal[:\s]+(\w+)", "signal"),
            # Specific tool failures
            (r"(dumpyara|uvx|aria2c|wget|git).*failed.*?:?\s*(.{10,100})", "tool_failure"),
        ]

        for pattern, cause_type in root_cause_patterns:
            match = re.search(pattern, console_log, re.IGNORECASE | re.DOTALL)
            if match:
                if cause_type == "tool_failure":
                    root_cause = f"{match.group(1)} failed: {match.group(2).strip()}"
                else:
                    root_cause = match.group(1).strip()
                # Clean up the root cause
                root_cause = re.sub(r'\s+', ' ', root_cause)  # Normalize whitespace
                root_cause = root_cause[:100]  # Limit length
                if root_cause and len(root_cause) > 5:
                    context["root_cause"] = root_cause
                    break

        # Enhanced build properties extraction
        build_props = []

        # Android version patterns
        version_patterns = [
            r"ro\.build\.version\.release=([^\s\n]+)",
            r"android[:\s]*(\d+(?:\.\d+)*)",
            r"api[:\s]*level[:\s]*(\d+)",
            r"sdk[:\s]*version[:\s]*(\d+)",
            # Jenkins pipeline format
            r"release[:\s]+(\d+(?:\.\d+)*)"
        ]

        for pattern in version_patterns:
            match = re.search(pattern, console_log, re.IGNORECASE)
            if match:
                version = match.group(1)
                if version.isdigit() and int(version) > 15:  # API level
                    build_props.append(f"API {version}")
                else:
                    build_props.append(f"Android {version}")
                break

        # Device codename patterns
        codename_patterns = [
            r"ro\.product\.device=([^\s\n]+)",
            r"ro\.build\.product=([^\s\n]+)",
            r"codename[:\s]*([a-zA-Z0-9_-]+)",
            r"device[:\s]*([a-zA-Z0-9_-]+)",
            # Jenkins pipeline format
            r"flavor[:\s]+([a-zA-Z0-9_-]+)",
            r"top_codename[:\s]+([a-zA-Z0-9_-]+)"
        ]

        for pattern in codename_patterns:
            match = re.search(pattern, console_log, re.IGNORECASE)
            if match:
                codename = match.group(1).strip()
                if codename and len(codename) > 2 and not codename.startswith('$'):
                    build_props.append(codename)
                break

        # Build ID/incremental
        build_id_patterns = [
            r"ro\.build\.id=([^\s\n]+)",
            r"ro\.build\.version\.incremental=([^\s\n]+)",
            r"build[:\s]*id[:\s]*([A-Za-z0-9._-]+)",
            # Jenkins pipeline format
            r"id[:\s]+([A-Za-z0-9._-]+)",
            r"incremental[:\s]+(\d+)"
        ]

        for pattern in build_id_patterns:
            match = re.search(pattern, console_log, re.IGNORECASE)
            if match:
                build_id = match.group(1).strip()
                if build_id and len(build_id) > 3:
                    build_props.append(f"Build {build_id}")
                break

        # ROM/UI version
        ui_patterns = [
            r"ro\.miui\.ui\.version\.name=([^\s\n]+)",
            r"ro\.build\.version\.oneui=([^\s\n]+)",
            r"ro\.oppo\.version=([^\s\n]+)",
            r"(miui|emui|one\s*ui|coloros|funtouch|oxygenos)[:\s]*([^\s\n]+)"
        ]

        for pattern in ui_patterns:
            match = re.search(pattern, console_log, re.IGNORECASE)
            if match:
                if match.lastindex == 2:  # Two groups
                    ui_name = match.group(1).upper()
                    ui_version = match.group(2).strip()
                    build_props.append(f"{ui_name} {ui_version}")
                else:
                    ui_version = match.group(1).strip()
                    build_props.append(ui_version)
                break

        # Combine build properties
        if build_props:
            context["build_properties"] = ", ".join(build_props[:3])  # Limit to 3 properties

        # Debug logging for improved extraction
        logger.debug(f"Context extraction results:")
        logger.debug(f"  Device Brand: {context['device_brand']}")
        logger.debug(f"  Firmware URL: {context['firmware_url'][:50]}..." if len(context['firmware_url']) > 50 else f"  Firmware URL: {context['firmware_url']}")
        logger.debug(f"  Error Category: {context['error_category']}")
        logger.debug(f"  Root Cause: {context['root_cause']}")
        logger.debug(f"  Build Properties: {context['build_properties']}")

        return context


    def _select_context_aware_template(self, error_category: str) -> int:
        """Select a template index with context-aware weighting."""
        import secrets

        # Get template names (extract from templates for matching)
        template_names = []
        for template in IMAGE_GENERATION_PROMPT_TEMPLATES:
            # Extract template name from comment line
            lines = template.strip().split('\n')
            for line in lines:
                if line.strip().startswith('# Template'):
                    name = line.split(':', 1)[-1].strip()
                    template_names.append(name)
                    break
            else:
                template_names.append("Generic Template")

        logger.debug(f"Template selection debug:")
        logger.debug(f"  Error category: '{error_category}'")
        logger.debug(f"  Available templates: {template_names}")

        # Check if we have context-specific weights
        if error_category in THEME_CONTEXT_WEIGHTS:
            weights = THEME_CONTEXT_WEIGHTS[error_category]
            logger.debug(f"  Found context weights: {weights}")

            # Create weighted list
            weighted_indices = []
            for i, name in enumerate(template_names):
                weight = weights.get(name, 1)  # Default weight of 1
                weighted_indices.extend([i] * weight)
                if weight > 1:
                    logger.debug(f"    Template {i} ('{name}') weighted {weight}x")

            if weighted_indices:
                selected_index = secrets.choice(weighted_indices)
                logger.debug(f"  Selected index {selected_index} from weighted list: {weighted_indices}")
                return selected_index

        # Fallback to random selection
        selected_index = secrets.randbelow(len(IMAGE_GENERATION_PROMPT_TEMPLATES))
        logger.debug(f"  Using random fallback, selected index: {selected_index}")
        return selected_index

    def _select_context_aware_background(self, template_name: str, error_category: str) -> str:
        """Select background with context-aware selection based on error type."""
        import secrets

        # Error category mapping to background themes
        category_backgrounds = {
            "Download": "space_age",  # Network/communication themes
            "Extraction": "mission_control",  # Processing/analysis themes
            "GitLab": "submarine",  # Storage/deployment themes
            "Network": "space_age",  # Connectivity themes
            "Storage": "submarine",  # Data management themes
        }

        # Get appropriate background category
        bg_category = category_backgrounds.get(error_category, "space_age")

        # Select from available backgrounds
        backgrounds = DYNAMIC_BACKGROUNDS.get(bg_category, DYNAMIC_BACKGROUNDS["space_age"])

        # Use random selection for variety
        return secrets.choice(backgrounds)

    def _get_dynamic_tech_element(self, template_name: str, error_category: str) -> str:
        """Get a random tech element appropriate for the template and context."""
        import secrets

        # Determine which tech element category to use based on template
        if "Retro" in template_name or "Vintage" in template_name:
            category = "retro"
        elif "Space" in template_name or "Futuristic" in template_name or "Mission Control" in template_name:
            category = "futuristic"
        elif "Emergency" in template_name:
            category = "emergency"
        elif "Factory" in template_name or "Assembly" in template_name:
            category = "industrial"
        else:
            category = "general"

        # Get appropriate tech elements
        elements = DYNAMIC_TECH_ELEMENTS.get(category, DYNAMIC_TECH_ELEMENTS["general"])
        selected_element = secrets.choice(elements)

        return f"**{selected_element}** that the animals are curiously investigating"

    def _enhance_template_with_dynamic_elements(self, template: str, template_name: str, error_category: str) -> str:
        """Inject dynamic elements into template placeholders."""
        import secrets

        logger.debug(f"Dynamic enhancement debug:")
        logger.debug(f"  Template name: '{template_name}'")
        logger.debug(f"  Error category: '{error_category}'")

        # Replace {dynamic_tech_element} placeholder
        tech_element = self._get_dynamic_tech_element(template_name, error_category)
        original_tech_count = template.count("{dynamic_tech_element}")
        template = template.replace("{dynamic_tech_element}", tech_element)
        logger.debug(f"  Replaced {original_tech_count} tech element placeholders with: {tech_element[:50]}...")

        # Replace {dynamic_background} placeholder
        if "{dynamic_background}" in template:
            background = self._select_context_aware_background(template_name, error_category)
            template = template.replace("{dynamic_background}", background)
            logger.debug(f"  Added dynamic background: {background[:50]}...")

        # Add some extra dynamic variations if template doesn't have enough randomness
        if "{dynamic_animal}" in template:
            # Add random animal variation
            all_animals = ANIMAL_VARIATIONS["cats"] + ANIMAL_VARIATIONS["parrots"] + ANIMAL_VARIATIONS["additional"]
            random_animal = secrets.choice(all_animals)
            template = template.replace("{dynamic_animal}", random_animal)
            logger.debug(f"  Added dynamic animal: {random_animal}")

        if "{dynamic_activity}" in template:
            # Add random activity
            activity = secrets.choice(ACTIVITY_VARIATIONS)
            template = template.replace("{dynamic_activity}", activity)
            logger.debug(f"  Added dynamic activity: {activity}")

        if "{dynamic_mood}" in template:
            # Add environmental mood
            mood = secrets.choice(ENVIRONMENTAL_MOODS)
            template = template.replace("{dynamic_mood}", mood)
            logger.debug(f"  Added dynamic mood: {mood}")

        # Ensure we always mention specific animals (cats and parrots)
        if "cats" not in template.lower() or "parrots" not in template.lower():
            logger.debug("  Template missing explicit animal mentions, this is a problem!")

        # Add explicit animal instruction at the beginning if not clear enough
        if "Generate a realistic but funny image" in template:
            template = template.replace(
                "Generate a realistic but funny image",
                "Generate a realistic but funny image featuring cats and parrots as the main characters"
            )
            logger.debug("  Enhanced opening instruction to specify cats and parrots")

        return template

    async def generate_surprise_image(
        self, console_log: str, build_info: Optional[Dict[str, Any]] = None, debug_build_number: Optional[int] = None
    ) -> Optional[bytes]:
        """
        Generate a surprise image based on Jenkins console log using Gemini 2.5 Flash Image.

        Args:
            console_log: The raw Jenkins console log text (ignored if debug_build_number is provided)
            build_info: Optional build metadata (job name, build number, etc.)
            debug_build_number: Optional specific Jenkins build number to fetch and analyze instead of using provided console_log

        Returns:
            Image bytes or None if generation fails
        """
        if not self.is_available():
            console.print(
                "[yellow]Gemini image generator not available - skipping image generation[/yellow]"
            )
            return None

        try:
            # Handle debug build number - fetch specific Jenkins build
            if debug_build_number is not None:
                console.print(f"[magenta]🔧 DEBUG MODE: Fetching Jenkins build #{debug_build_number}[/magenta]")

                try:
                    from dumpyarabot.utils import get_jenkins_console_log

                    # Use the existing utility function to fetch console log
                    fetched_console_log = await get_jenkins_console_log("dumpyara", str(debug_build_number))

                    if not fetched_console_log or len(fetched_console_log.strip()) < 50:
                        console.print("[red]Failed to fetch Jenkins build log or log too short, aborting image generation[/red]")
                        return None

                    # Use the fetched log instead of the provided one
                    console_log = fetched_console_log
                    console.print(f"[green]Using console log from Jenkins build #{debug_build_number} ({len(console_log)} chars)[/green]")

                except Exception as e:
                    console.print(f"[red]Error fetching Jenkins build #{debug_build_number}: {e}[/red]")
                    logger.error(f"Jenkins console log fetch failed for build {debug_build_number}: {e}")
                    return None

            # Now check console log size after potential debug fetch
            if not console_log or len(console_log.strip()) < 50:
                console.print(
                    "[yellow]Console log too short for meaningful image generation[/yellow]"
                )
                return None

            # Extract context from log (either provided or fetched)
            context = self._extract_context_from_log(console_log)

            console.print("[blue]Extracted context for image generation:[/blue]")
            console.print(f"  Device Brand: {context['device_brand']}")
            console.print(f"  Error Category: {context['error_category']}")

            # Use context-aware template selection
            template_index = self._select_context_aware_template(context['error_category'])
            selected_template = IMAGE_GENERATION_PROMPT_TEMPLATES[template_index]

            # Extract template name for dynamic enhancement
            template_name = "Generic Template"
            lines = selected_template.strip().split('\n')
            for line in lines:
                if line.strip().startswith('# Template'):
                    template_name = line.split(':', 1)[-1].strip()
                    break

            # Debug: log template extraction
            logger.debug(f"Template index: {template_index}, Template lines: {[l.strip() for l in lines[:5] if l.strip()]}")
            logger.debug(f"Extracted template name: '{template_name}'")

            # Show template selection method
            if debug_build_number is not None:
                selection_method = f"DEBUG BUILD #{debug_build_number}"
                color = "magenta"
            else:
                selection_method = "context-aware"
                color = "blue"

            console.print(
                f"[{color}]Using template #{template_index + 1}: {template_name} ({selection_method})[/{color}]"
            )

            # Enhance template with dynamic elements
            enhanced_template = self._enhance_template_with_dynamic_elements(
                selected_template, template_name, context['error_category']
            )

            # Create a focused prompt for image generation based on the enhanced template
            focused_prompt = enhanced_template.format(**context)

            # Debug logging: show final prompt for debugging
            console.print("[cyan]Final prompt (debug):[/cyan]")
            console.print("=" * 50)
            console.print(focused_prompt)
            console.print("=" * 50)

            logger.debug(f"Full generated prompt for template '{template_name}': {focused_prompt}")

            console.print(
                "[blue]Generating surprise image with Gemini 2.5-flash...[/blue]"
            )

            try:
                # Use the correct Google GenAI API for image generation with 2.5-flash
                response = self.client.models.generate_content(
                    model="gemini-2.5-flash-image-preview", contents=[focused_prompt]
                )

                # Process the response parts looking for image data or text response
                gemini_text_response = None

                for part in response.candidates[0].content.parts:
                    if part.text is not None:
                        gemini_text_response = part.text.strip()
                        console.print(
                            f"[blue]Text response: {gemini_text_response[:100]}...[/blue]"
                        )

                    elif part.inline_data is not None:
                        console.print(
                            "[green]Image generated successfully by Gemini 2.5-flash![/green]"
                        )

                        # Save the image using PIL and return bytes
                        try:
                            image = Image.open(BytesIO(part.inline_data.data))

                            # Convert to bytes for return
                            img_bytes = BytesIO()
                            image.save(img_bytes, format="PNG")
                            img_bytes.seek(0)

                            console.print(
                                f"[green]Image size: {image.size}, format: {image.format}[/green]"
                            )
                            return img_bytes.getvalue()

                        except Exception as img_error:
                            console.print(
                                f"[yellow]Failed to process image data: {img_error}[/yellow]"
                            )
                            # Return raw image data as fallback
                            return part.inline_data.data

                # If we get here, no image was generated
                console.print("[yellow]No image generated by Gemini 2.5-flash[/yellow]")

                # Create a fallback using actual Gemini text response if available
                def escape_markdown_basic(text: str) -> str:
                    """Escape basic problematic characters for Telegram Markdown."""
                    return text.replace("_", "\\_").replace("*", "\\*")

                device_brand = escape_markdown_basic(context["device_brand"])
                error_category = escape_markdown_basic(context["error_category"])
                build_properties = escape_markdown_basic(context["build_properties"])

                if gemini_text_response and len(gemini_text_response) > 20:
                    # Use the actual Gemini text response
                    escaped_response = escape_markdown_basic(gemini_text_response[:500])  # Limit length
                    description = f"🤖 **Gemini AI Response:**\n\n{escaped_response}\n\n📱 **Technical Context:**\n• Device: {device_brand}\n• Issue: {error_category}\n• Properties: {build_properties}\n\n*Image generation returned text instead of image*"
                else:
                    # Generic fallback only if no meaningful text response
                    description = f"🎨 **Creative Scene Description:**\n\nImagine a whimsical tech lab where cats and parrots are working on {device_brand} firmware dumps. The 'Dumpyara' logo is prominently displayed on monitors showing {error_category} errors. The animals wear tiny lab coats and seem focused on debugging the firmware extraction process.\n\n📱 **Technical Context:**\n• Device: {device_brand}\n• Issue: {error_category}\n• Properties: {build_properties}\n\n*Image generation failed - no response from Gemini*"

                return description.encode("utf-8")

            except Exception as api_error:
                console.print(f"[red]Gemini API error: {api_error}[/red]")
                logger.error(f"Gemini image generation API error: {api_error}")

                # Return error context as text with minimal escaping
                device_brand = escape_markdown_basic(context["device_brand"])
                error_category = escape_markdown_basic(context["error_category"])
                build_properties = escape_markdown_basic(context["build_properties"])
                api_error_str = escape_markdown_basic(str(api_error)[:100])

                error_description = f"❌ **Image Generation Failed**\n\nAttempted to generate an image of cats and parrots in a tech environment working on {device_brand} firmware with 'Dumpyara' branding, but encountered an API error.\n\n📱 **Technical Context:**\n• Device: {device_brand}\n• Issue: {error_category}\n• Properties: {build_properties}\n\n*Error: {api_error_str}...*"

                return error_description.encode("utf-8")

        except Exception as e:
            console.print(f"[red]Failed to generate surprise image: {e}[/red]")
            logger.error(f"Gemini image generation failed: {e}")
            return None


# Create global instances
analyzer = GeminiLogAnalyzer()
image_generator = GeminiImageGenerator()
