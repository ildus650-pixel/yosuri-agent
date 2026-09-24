#!/usr/bin/env python3
"""Regression suite for answer_challenge() in hansa_cycle.py.

Every case is a real challenge the platform issued, harvested from the cycle
reports in hansa/*.md. The ones the API accepted came back verify 200 and are
recorded with the answer it took; the eleven that came back verify 400 are
recorded with the value the platform expects. That pins down the templates
which used to fail - "N dozen ... minus M", "split N into groups of M ... left
over" and "A has N. B has twice as many" - so they cannot regress quietly.

Run: python3 scripts/test_hansa_solver.py
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "hansa_cycle", os.path.join(HERE, "hansa_cycle.py"))
hc = importlib.util.module_from_spec(spec)
sys.modules["hansa_cycle"] = hc
try:
    spec.loader.exec_module(hc)
except SystemExit:
    pass

CASES = [
    ('A parrot has 20 tickets and gives away half. How many are left?', 10),
    ('A monkey has 12 tickets. It gains two more and loses 12. How many?', 2),
    ('A basket contains a dozen berries minus 2. How many?', 10),
    ('A astronaut collects three acorns in the morning and 7 in the afternoon, then shares half with a friend. How many acorns does the astronaut keep?', 5),
    ('4 bears each carry two keys. How many keys in total?', 8),
    ('What is 20 plus 13 tickets?', 33),
    ('A bear tries to split 29 coins into groups of 3. How many coins are left over?', 2),
    ('A baker has six shells and triples the collection. How many now?', 18),
    ('A chef numbers its stars from four to 14 inclusive. How many stars is that?', 11),
    ('A dragon has 16 pebbles. A captain has 12 fewer. How many pebbles does the captain have?', 4),
    ('A parrot has 7 berries and triples the collection. How many now?', 21),
    ('A bear doubles its ten ribbons and then finds 6 more. How many total?', 26),
    ('A bear has 16 badges. A wizard has 5 more than the bear. How many badges does the wizard have?', 21),
    ('A bear starts with 2 shells, finds three more, then gives away four. The sky was cloudy that day. How many shells does the bear have now?', 1),
    ('A basket contains two dozen coins minus 21. How many?', 3),
    ('A basket contains three dozen cookies minus 17. How many?', 19),
    ('A raccoon has ten mushrooms. It gains 4 more and loses five. How many?', 9),
    ('If you subtract 14 from 15 tickets, what remains?', 1),
    ('A chef has 20 gems. A fox has eleven fewer. How many gems does the fox have?', 9),
    ('A knight collects ten pebbles in the morning and 10 in the afternoon, then shares half with a friend. How many pebbles does the knight keep?', 10),
    ('A astronaut has 10 pebbles and gives away half. How many are left?', 5),
    ('If you subtract 17 from 18 berries, what remains?', 1),
    ('A basket contains two dozen cookies minus 1. How many?', 23),
    ('What is the sum of twelve and 4 crystals?', 16),
    ('A baker doubles its 7 fish and then finds 7 more. How many total?', 21),
    ('14 stars are split evenly among two wizards. How many stars per wizard?', 7),
    ('A bear has 4 shells and gives away half. How many are left?', 2),
    ('A dragon has 9 acorns. A fox has 3 more than the dragon. How many acorns does the fox have?', 12),
    ('20 books are split evenly among five raccoons. How many books per raccoon?', 4),
    ('A chef has 4 badges and triples the collection. How many now?', 12),
    ('What is the sum of five and 11 mushrooms?', 16),
    ('A farmer starts with 4 badges, finds 7 more, then gives away 4. It was a particularly warm afternoon. How many badges does the farmer have now?', 7),
    ('What is the sum of twelve and 8 tickets?', 20),
    ('A basket contains three dozen mushrooms minus 12. How many?', 24),
    ('A cat numbers its badges from 4 to 10 inclusive. How many badges is that?', 7),
    ('What is 16 plus nine books?', 25),
    ('A owl begins with nine keys. A bell rang in the distance. Then it finds 5 more. Everything else stayed perfectly still. Finally it loses 5. How many keys remain?', 9),
    ('A chef doubles its 2 ribbons and then finds 6 more. How many total?', 10),
    ('A fox collects 10 cookies in the morning and six in the afternoon, then shares half with a friend. How many cookies does the fox keep?', 8),
    ('16 apples are split evenly among 4 cats. How many apples per cat?', 4),
    ('A penguin has 11 ribbons. A cat has twice as many. How many ribbons does the cat have?', 22),
    ('eight parrots each carry 5 coins. How many coins in total?', 40),
    ('There are 8 books on Monday and a wizard brings 15 more on Tuesday. The leaves rustled softly. What is the total?', 23),
    ('There are 10 apples on Monday and a wizard brings 6 more on Tuesday. Everything else stayed perfectly still. What is the total?', 16),
    ('A wizard has 14 gems and gives away half. How many are left?', 7),
    ('There are 8 coins on Monday and a wizard brings 15 more on Tuesday. Nobody noticed anything unusual. What is the total?', 23),
    ('A penguin has 7 acorns and triples the collection. How many now?', 21),
    ('A basket contains two dozen gems minus two. How many?', 22),
    ('12 coins are split evenly among four wizards. How many coins per wizard?', 3),
    ('A bear has 25 ribbons. A dolphin has 18 fewer. How many ribbons does the dolphin have?', 7),
    ('A basket contains a dozen berries minus 1. How many?', 11),
    ('If you subtract nine from 16 marbles, what remains?', 7),
    ('A bear begins with 5 stars. It was a particularly warm afternoon. Then it finds 1 more. Nobody noticed anything unusual. Finally it loses three. How many stars remain?', 3),
    ('A robot collects six stars in the morning and four in the afternoon, then shares half with a friend. How many stars does the robot keep?', 5),
    ('A farmer has 11 fish. A dragon has 9 more than the farmer. How many fish does the dragon have?', 20),
    ('A wizard begins with 14 apples. Someone nearby was humming a tune. Then it finds 4 more. The leaves rustled softly. Finally it loses 5. How many apples remain?', 13),
    ('A raccoon tries to split 23 crystals into groups of 5. How many crystals are left over?', 3),
    ('24 pebbles are split evenly among four foxs. How many pebbles per fox?', 6),
    ('A knight has 9 fish. It gains 1 more and loses seven. How many?', 3),
    ('A captain has 3 marbles. It gains 5 more and loses 3. How many?', 5),
    ('A raccoon numbers its berries from 1 to ten inclusive. How many berries is that?', 10),
    ('A pirate has 7 shells. It gains 2 more and loses 3. How many?', 6),
    ('A dragon numbers its gems from 4 to 10 inclusive. How many gems is that?', 7),
    ('A fox has 10 keys. A captain has twice as many. How many keys does the captain have?', 20),
    ('A farmer has 6 coins. A monkey has 1 more than the farmer. How many coins does the monkey have?', 7),
    ('A dolphin has 15 crystals. It gains 8 more and loses four. How many?', 19),
    ('4 raccoons each carry 4 coins. How many coins in total?', 16),
    ('A cat has 10 mushrooms. A pirate has twice as many. How many mushrooms does the pirate have?', 20),
    ('There are 15 ribbons on Monday and a dragon brings 9 more on Tuesday. Someone nearby was humming a tune. What is the total?', 24),
    ('A astronaut tries to split 11 mushrooms into groups of seven. How many mushrooms are left over?', 4),
    ('If you subtract 7 from 14 cookies, what remains?', 7),
    ('A owl doubles its 6 shells and then finds 2 more. How many total?', 14),
    ('A squirrel has 4 acorns and triples the collection. How many now?', 12),
    ('A wizard begins with 12 acorns. A gentle breeze blew from the east. Then it finds 4 more. A bell rang in the distance. Finally it loses 5. How many acorns remain?', 11),
    ('5 bakers each carry 6 ribbons. How many ribbons in total?', 30),
    ('A pirate has 22 gems and gives away half. How many are left?', 11),
]


def main():
    bad = []
    for question, expected in CASES:
        try:
            got = hc.answer_challenge(question)
        except Exception as exc:                       # noqa: BLE001
            got = "raised {}".format(exc)
        if str(got) != str(expected):
            bad.append((question, expected, got))
    print("{}/{} cases pass".format(len(CASES) - len(bad), len(CASES)))
    for question, expected, got in bad:
        print("  FAIL expected {} got {} | {}".format(expected, got, question))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
