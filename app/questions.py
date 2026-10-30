"""Original practice questions (not copied from the inspected upstream repository)."""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Question:
    id: str
    part: int
    topic: str
    prompt: str
    cues: tuple[str, ...] = ()

    def serialize(self) -> dict:
        return {**asdict(self), 'cues': list(self.cues)}


QUESTIONS: tuple[Question, ...] = (
    Question('p1-study-1', 1, 'Study & Work', 'What is one thing you enjoy most about what you study or do?'),
    Question('p1-study-2', 1, 'Study & Work', 'Do you prefer working alone or with other people? Why?'),
    Question('p1-study-3', 1, 'Study & Work', 'Has your daily routine changed since you started studying or working?'),
    Question('p1-home-1', 1, 'Home & Hometown', 'Which place in your hometown would you recommend to a visitor?'),
    Question('p1-home-2', 1, 'Home & Hometown', 'What is something you would change about your neighbourhood?'),
    Question('p1-home-3', 1, 'Home & Hometown', 'Would you like to live in the same city in the future?'),
    Question('p1-food-1', 1, 'Food & Habits', 'What kind of meal do you usually eat when you are busy?'),
    Question('p1-food-2', 1, 'Food & Habits', 'Have your food preferences changed over the years?'),
    Question('p1-food-3', 1, 'Food & Habits', 'Do you think cooking is an important skill for young people?'),
    Question('p1-tech-1', 1, 'Technology', 'What piece of technology do you use most often during the day?'),
    Question('p1-tech-2', 1, 'Technology', 'Are there any apps you have stopped using recently? Why?'),
    Question('p1-tech-3', 1, 'Technology', 'Do you prefer learning new things online or in a classroom?'),
    Question('p1-free-1', 1, 'Free Time', 'What do you usually do when you unexpectedly have a free afternoon?'),
    Question('p1-free-2', 1, 'Free Time', 'Is there a hobby you would like to try this year?'),
    Question('p1-free-3', 1, 'Free Time', 'Do you spend your weekends differently from when you were younger?'),
    Question('p1-travel-1', 1, 'Travel', 'Do you prefer planning a trip carefully or making decisions as you go?'),
    Question('p1-travel-2', 1, 'Travel', 'What is the most convenient way to travel around your city?'),
    Question('p1-travel-3', 1, 'Travel', 'Have you ever changed your opinion about a place after visiting it?'),

    Question('p2-tech-1', 2, 'Technology', 'Describe a digital tool that made a task easier for you.',
             ('What the tool is', 'How you first discovered it', 'How you use it', 'Why it made a difference')),
    Question('p2-tech-2', 2, 'Technology', 'Describe a time when you learned a useful skill from the internet.',
             ('What you wanted to learn', 'Which resources helped', 'What was difficult', 'How you use the skill today')),
    Question('p2-people-1', 2, 'People', 'Describe someone who helped you become more confident.',
             ('Who this person is', 'How you know them', 'What they did', 'How your confidence changed')),
    Question('p2-travel-1', 2, 'Travel', 'Describe an unexpected experience you had while travelling.',
             ('Where you were going', 'What happened', 'How you responded', 'Why you still remember it')),
    Question('p2-education-1', 2, 'Education', 'Describe a project you completed that taught you an important lesson.',
             ('What the project was', 'Who worked on it', 'What challenge arose', 'What lesson you learned')),
    Question('p2-environment-1', 2, 'Environment', 'Describe a place outdoors where you feel refreshed.',
             ('Where it is', 'What it looks like', 'What you do there', 'Why this place matters to you')),
    Question('p2-community-1', 2, 'Community', 'Describe a local event that brought people together.',
             ('When and where it happened', 'Who took part', 'What activities took place', 'How it affected the community')),

    Question('p3-tech-1', 3, 'Technology', 'How has technology changed the way people solve everyday problems?'),
    Question('p3-tech-2', 3, 'Technology', 'Should schools spend more time teaching students to evaluate online information?'),
    Question('p3-tech-3', 3, 'Technology', 'What are some disadvantages of depending on digital tools?'),
    Question('p3-tech-4', 3, 'Technology', 'Will artificial intelligence make people more or less creative?'),
    Question('p3-people-1', 3, 'People', 'What qualities make a person an effective mentor?'),
    Question('p3-people-2', 3, 'People', 'Is confidence mainly developed through experience or encouragement?'),
    Question('p3-people-3', 3, 'People', 'How can workplaces help new employees feel included?'),
    Question('p3-people-4', 3, 'People', 'Do people learn important lessons more often from friends or family?'),
    Question('p3-travel-1', 3, 'Travel', 'In what ways does tourism benefit small communities?'),
    Question('p3-travel-2', 3, 'Travel', 'Why do some travellers prefer less familiar destinations?'),
    Question('p3-travel-3', 3, 'Travel', 'Should governments limit visitor numbers at popular sites?'),
    Question('p3-travel-4', 3, 'Travel', 'How might the way people travel change in the next twenty years?'),
    Question('p3-education-1', 3, 'Education', 'How should schools balance teamwork and individual achievement?'),
    Question('p3-education-2', 3, 'Education', 'What is the value of learning from an unsuccessful project?'),
    Question('p3-education-3', 3, 'Education', 'Will practical skills become more important in education in the future?'),
    Question('p3-education-4', 3, 'Education', 'What role should mistakes play in the learning process?'),
    Question('p3-environment-1', 3, 'Environment', 'Why is access to green space important in cities?'),
    Question('p3-environment-2', 3, 'Environment', 'Who should take more responsibility for protecting natural areas?'),
    Question('p3-environment-3', 3, 'Environment', 'Can tourism and environmental protection work together?'),
    Question('p3-environment-4', 3, 'Environment', 'How can a city encourage people to spend more time outdoors?'),
    Question('p3-community-1', 3, 'Community', 'What kinds of events strengthen relationships between neighbours?'),
    Question('p3-community-2', 3, 'Community', 'How has social media changed participation in local activities?'),
    Question('p3-community-3', 3, 'Community', 'Should cities invest more in public meeting spaces?'),
    Question('p3-community-4', 3, 'Community', 'Why do some young adults feel less connected to their neighbourhoods?'),
)

BY_ID = {q.id: q for q in QUESTIONS}


def all_questions(part: int | None = None, topic: str | None = None) -> list[dict]:
    return [q.serialize() for q in QUESTIONS if (part is None or q.part == part)
            and (topic is None or q.topic == topic)]


def mock_questions(seed: int | None = None) -> list[dict]:
    rng = random.Random(seed)
    first = rng.sample([q for q in QUESTIONS if q.part == 1], 5)
    cue = rng.choice([q for q in QUESTIONS if q.part == 2])
    discussion = rng.sample([q for q in QUESTIONS if q.part == 3 and q.topic == cue.topic], 4)
    return [q.serialize() for q in [*first, cue, *discussion]]
