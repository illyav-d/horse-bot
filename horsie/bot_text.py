"""Small pools of horse nonsense, without repeating a line back to back."""

import random


LINES = {
    "horse_caption": [
        "Daily horse delivery.", "A horse has arrived.", "Neigh.",
        "Your regularly scheduled horse interruption.",
        "Fresh from the pasture, with absolutely no qualifications.",
        "The stable has approved this message.",
        "A small contribution to the server's horse population.",
        "Please welcome today's hay-powered guest.",
        "Another day, another professional grass inspector.",
        "The horse department would like your attention.",
    ],
    "horse_title": [
        "Horse of the Day", "Today's Stable Visitor", "Fresh from the Pasture",
        "An Important Horse Update", "The Daily Neigh",
    ],
    "fact_intro": [
        "Horse fact", "A note from the stable library", "Today's equine knowledge",
        "The horse professor reports", "Pasture trivia",
    ],
    "carrots_self": [
        "🥕 You have **{count}** carrot(s).",
        "🥕 Your snack treasury contains **{count}** carrot(s).",
        "🥕 The stable accountant counted **{count}** carrot(s) in your name.",
        "🥕 Carrot inspection complete: **{count}** carrot(s). All crunchy.",
    ],
    "carrots_other": [
        "🥕 **{name}** has **{count}** carrot(s).",
        "🥕 The carrot vault lists **{count}** carrot(s) for **{name}**.",
        "🥕 **{name}** is sitting on a fortune of **{count}** carrot(s).",
        "🥕 Stable audit: **{name}** owns **{count}** carrot(s).",
    ],
    "empty_leaderboard": [
        "🥕 The carrot leaderboard is empty. Win a game to earn the first carrot!",
        "🥕 No carrot tycoons yet. Win a game and claim the top spot!",
        "🥕 The stable accountant has nothing to count. Win a game to fix that!",
    ],
    "bets_closed": [
        "🔔 Bets are closed! The horses are being gently convinced to face the correct direction...",
        "🔔 Pencils down, hooves up! The horses are approaching the starting gate.",
        "🔔 All picks are locked. Someone please explain the finish line to the horses.",
        "🔔 Betting is over! The athletes have finished their pre-race grass inspection.",
        "🔔 The betting window is shut. The carrot economy is now in the hands of four horses.",
    ],
    "race_no_winners": [
        "🐴 The horse celebrates alone, which is honestly very powerful.",
        "🐴 The winner would like to thank absolutely none of the bettors.",
        "🐴 A stunning victory for the horse and a difficult evening for sports journalism.",
        "🐴 The horse has requested a new audience with better instincts.",
    ],
    "horsejack_intro": [
        "The dealer shuffles with suspiciously confident hooves.",
        "A horse in a tiny waistcoat invites you to the table.",
        "Welcome to the only casino where the dealer might eat the cards.",
        "The stable's least qualified mathematician is ready to deal.",
    ],
    "horsejack_bust": [
        "💥 You busted! The dealer horse slowly eats your paperwork.",
        "💥 Over 21! The dealer stamps your hand 'too much ambition'.",
        "💥 You busted. Somewhere, a calculator neighs in disappointment.",
        "💥 Too many points! The horse offers you a sympathetic mouthful of hay.",
    ],
    "horsejack_timeout": [
        "⌛ You waited too long. The dealer horse got bored and wandered away.",
        "⌛ Time's up! The dealer has left for an urgent grass appointment.",
        "⌛ The horse waited 30 seconds, then ate the reservation. Game over.",
    ],
    "horsejack_hit": [
        "🃏 You draw another card. The horse squints judgmentally.",
        "🃏 Another card slides across the table. It smells faintly of hay.",
        "🃏 One more card. The dealer raises what might be an eyebrow.",
        "🃏 You take a card. The horse makes a note in a very small notebook.",
    ],
    "horsejack_dealer_bust": [
        "🏆 Dealer horse busted! You win 🥕 **1 carrot**.",
        "🏆 The dealer went over 21 and blames the hoof arithmetic. You win 🥕 **1 carrot**!",
        "🏆 Too many points for the horse! Collect 🥕 **1 carrot** before it appeals.",
    ],
    "horsejack_win": [
        "🏆 You beat the dealer horse and win 🥕 **1 carrot**.",
        "🏆 A victory for opposable thumbs! You earn 🥕 **1 carrot**.",
        "🏆 The horse concedes with extremely poor grace. You win 🥕 **1 carrot**!",
    ],
    "horsejack_tie": [
        "🤝 Push! You tied with the dealer horse. No carrot, but your honor survives.",
        "🤝 A tie! The carrot stays in the vault and the horse demands a rematch.",
        "🤝 Even scores. No carrot changes hands, or hooves.",
    ],
    "horsejack_loss": [
        "🐴 Dealer horse wins. It looks far too smug. No carrot this time.",
        "🐴 The dealer wins and pretends this was advanced mathematics. No carrot this time.",
        "🐴 A win for the house, which is technically a barn. No carrot this time.",
    ],
    "macaroni": [
        "🐴 Macaroni horse has entered the kitchen.",
        "🍝 The chef has arrived. Qualifications: horse.",
        "🐴 Someone ordered pasta with extra neigh.",
        "🍝 The stable's head of catering would like a word.",
    ],
}

_last = {}


def line(key, **values):
    pool = LINES[key]
    choices = [text for text in pool if text != _last.get(key)] or pool
    text = random.choice(choices)
    _last[key] = text
    return text.format(**values)
