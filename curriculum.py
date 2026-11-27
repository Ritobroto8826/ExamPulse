"""The exact supported curriculum per class, in chapter order. No demo/legacy subjects.

Class 10 matches the CBSE/NCERT syllabus this app was built around. Class 8 and
9 follow the classic NCERT chapter lists; the school must verify them against
its own syllabus before first deployment. Keep this file and the topic seed in
supabase/migrations/ identical — the test suite enforces that agreement.
"""

CURRICULUM: dict[int, dict[str, list[str]]] = {
    8: {
        "Mathematics": [
            "Rational Numbers",
            "Linear Equations in One Variable",
            "Understanding Quadrilaterals",
            "Practical Geometry",
            "Data Handling",
            "Squares and Square Roots",
            "Cubes and Cube Roots",
            "Comparing Quantities",
            "Algebraic Expressions and Identities",
            "Visualising Solid Shapes",
            "Mensuration",
            "Exponents and Powers",
            "Direct and Inverse Proportions",
            "Factorisation",
            "Introduction to Graphs",
            "Playing with Numbers",
        ],
        "Science": [
            "Crop Production and Management",
            "Microorganisms: Friend and Foe",
            "Coal and Petroleum",
            "Combustion and Flame",
            "Conservation of Plants and Animals",
            "Reproduction in Animals",
            "Reaching the Age of Adolescence",
            "Force and Pressure",
            "Friction",
            "Sound",
            "Chemical Effects of Electric Current",
            "Some Natural Phenomena",
            "Light",
            "Stars and the Solar System",
            "Pollution of Air and Water",
        ],
    },
    9: {
        "Mathematics": [
            "Number Systems",
            "Polynomials",
            "Coordinate Geometry",
            "Linear Equations in Two Variables",
            "Introduction to Euclid's Geometry",
            "Lines and Angles",
            "Triangles",
            "Quadrilaterals",
            "Areas of Parallelograms and Triangles",
            "Circles",
            "Constructions",
            "Heron's Formula",
            "Surface Areas and Volumes",
            "Statistics",
            "Probability",
        ],
        "Science": [
            "Matter in Our Surroundings",
            "Is Matter Around Us Pure?",
            "Atoms and Molecules",
            "Structure of the Atom",
            "The Fundamental Unit of Life",
            "Tissues",
            "Motion",
            "Force and Laws of Motion",
            "Gravitation",
            "Work and Energy",
            "Sound",
            "Why Do We Fall Ill?",
            "Improvement in Food Resources",
        ],
    },
    10: {
        "Mathematics": [
            "Real Numbers",
            "Polynomials",
            "Pair of Linear Equations in Two Variables",
            "Quadratic Equations",
            "Arithmetic Progressions",
            "Triangles",
            "Coordinate Geometry",
            "Introduction to Trigonometry",
            "Some Applications of Trigonometry",
            "Circles",
            "Areas Related to Circles",
            "Surface Areas and Volumes",
            "Statistics",
            "Probability",
        ],
        "Science": [
            "Chemical Reactions and Equations",
            "Acids, Bases and Salts",
            "Metals and Non-metals",
            "Carbon and its Compounds",
            "Life Processes",
            "Control and Coordination",
            "How do Organisms Reproduce?",
            "Heredity",
            "Light – Reflection and Refraction",
            "The Human Eye and the Colourful World",
            "Electricity",
            "Magnetic Effects of Electric Current",
            "Our Environment",
        ],
    },
}

# Classes offered by this deployment, in ascending order. Extend by adding the
# class here and seeding its topics in supabase/migrations/ (both together).
CLASS_LEVELS = sorted(CURRICULUM)


def class_label(level: int) -> str:
    """Human label for a class level, e.g. 9 -> 'Class 9'."""
    return f"Class {int(level)}"


def chapters_for(level: int, subject: str) -> list[str]:
    """Chapter list for one class/subject; empty when unsupported."""
    return CURRICULUM.get(int(level), {}).get(subject, [])
