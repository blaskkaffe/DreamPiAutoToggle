#!/usr/bin/env python3
"""A roster for the tall, two-column screens: make_people.py N [seed] > people.csv

N people (20-80 is the range in use) in departments of 1 to 15 people, mostly 6 to 12 (the usual size), spread over two buildings. The names are
made from lists so that no two are alike; the same N and seed always give the same file."""
import random
import sys

FIRST = ("Anna Erik Maja Johan Karin Lars Sara Nils Ida Axel Klara Oskar Elin Simon Tove Viktor Greta Ola Eva Hugo Alva Ivar Lena Mats Nora Olle Pia Rolf Siv Ture "
         "Ulla Vera Waldemar Yrsa Åke Åsa Örjan Ebba Folke Gunnel Hilda Isak Jonna Kerstin Leif Märta Nina Oden Petra Ragnar Stina").split()
LAST = ("Svensson Lindqvist Holm Berg Lund Sandberg Ek Wikström Strand Öberg Nordin Åberg Dahl Nyström Forsberg Engström Hedlund Blom Sjöberg Lindgren Bergman Falk "
        "Håkansson Palm Roos Sundin Viklund Wallin Ström Eklund").split()
DEPTS = ("Administration Kök Servering Reception Lager Städ Ekonomi Personal Teknik Vård Barnomsorg Fritid Transport Underhåll Inköp").split()
WEIGHTS = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 8, 7: 9, 8: 10, 9: 10, 10: 9, 11: 7, 12: 6, 13: 2, 14: 1, 15: 1}      # 6 to 12 is the usual size


def sizes(n, rnd):
    """Group sizes that add up to n; from 36 people up the file has the extremes too: one group of 15 and one of 1."""
    out = [15, 1] if n >= 36 else []
    while sum(out) < n:
        out.append(rnd.choices(list(WEIGHTS), weights=list(WEIGHTS.values()))[0])
    out[-1] -= sum(out) - n
    return [s for s in out if s > 0]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    rnd = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    names = [f + " " + l for f in FIRST for l in LAST]
    rnd.shuffle(names)
    depts = DEPTS[:]
    rnd.shuffle(depts)
    print("name,department,role,phone,location,restrictToLocation")
    k = 0
    for i, size in enumerate(sizes(n, rnd)):
        dept = depts[i % len(depts)] + ("" if i < len(depts) else " %d" % (i // len(depts) + 1))
        for _ in range(size):
            print("%s,%s,%s,,%s," % (names[k], dept, rnd.choice(["Chef", "Medarbetare", "Vikarie"]), "Område A" if i % 2 == 0 else "Område B"))
            k += 1


if __name__ == "__main__":
    main()
