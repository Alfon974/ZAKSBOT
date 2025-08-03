import os
import time
import threading
import sqlite3

import discord
from discord.ext import commands, tasks
from flask import Flask

# --- 0) Base de données SQLite pour l'XP ---
conn = sqlite3.connect('xp.db')
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    xp INTEGER DEFAULT 0,
    last_voice_join INTEGER
)
''')
conn.commit()

def get_xp(user_id):
    cursor.execute('SELECT xp FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0

def set_xp(user_id, xp_value):
    new_xp = max(xp_value, 0)
    cursor.execute('INSERT OR IGNORE INTO users(user_id) VALUES(?)', (user_id,))
    cursor.execute('UPDATE users SET xp = ? WHERE user_id = ?', (new_xp, user_id))
    conn.commit()

def add_xp(user_id, amount):
    current = get_xp(user_id)
    set_xp(user_id, current + amount)


def set_voice_join(user_id, timestamp):
    cursor.execute('INSERT OR IGNORE INTO users(user_id) VALUES(?)', (user_id,))
    cursor.execute('UPDATE users SET last_voice_join = ? WHERE user_id = ?', (timestamp, user_id))
    conn.commit()

def pop_voice_join(user_id):
    cursor.execute('SELECT last_voice_join FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if not row or row[0] is None:
        return None
    t0 = row[0]
    cursor.execute('UPDATE users SET last_voice_join = NULL WHERE user_id = ?', (user_id,))
    conn.commit()
    return t0

# --- Paliers d’XP et conversion vers niveau [1-100] ---
MAX_XP = 10000  # XP nécessaire pour atteindre le niveau 100

def xp_to_level(xp: int) -> int:
    lvl = int(xp * 99 / MAX_XP) + 1
    return min(max(lvl, 1), 100)

LEVEL_ROLES = {
    0:    "ZAKS Rookie",
    1000: "ZAKS Gamers",
    5000: "ZAKS Elite"
}

async def maybe_level_up(member):
    xp = get_xp(member.id)
    eligible = [lvl for lvl in LEVEL_ROLES if lvl <= xp]
    if not eligible:
        return
    target = max(eligible)
    role_name = LEVEL_ROLES[target]
    role = discord.utils.get(member.guild.roles, name=role_name)
    if role and role not in member.roles:
        try:
            for lvl, name in LEVEL_ROLES.items():
                r = discord.utils.get(member.guild.roles, name=name)
                if r and r in member.roles:
                    await member.remove_roles(r)
            await member.add_roles(role)
            # log palier atteint
            log_ch = bot.get_channel(LEVEL_LOG_CHANNEL_ID)
            if log_ch:
                await log_ch.send(f"🏅 {member.mention} est maintenant **{role_name}** ({xp} XP) !")
        except discord.Forbidden:
            print(f"⚠️ Pas la permission pour gérer {role_name} pour {member}.")
        except Exception as e:
            print(f"❌ Erreur maybe_level_up pour {member}: {e}")

# --- 1) Flask pour Render ---
app = Flask(__name__)

@app.route('/')
def home():
    return "ZAKS BOT est en ligne !"

def run_flask():
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_flask).start()

# --- 2) Bot Discord ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# IDs salons
WELCOME_CHANNEL_ID = 1302027297116917922
LOGS_CHANNEL_ID    = 1400141141663547462  # salon logs général
LEVEL_LOG_CHANNEL_ID = 1401528018345787462  # salon XP/niveaux

# --- 3) Heartbeat ---
@tasks.loop(minutes=5)
async def heartbeat():
    try:
        await bot.change_presence(
            status=discord.Status.online,
            activity=discord.Game("ZAKS BOT")
        )
        print("💓 Heartbeat envoyé.")
    except Exception as e:
        print(f"❌ Erreur Heartbeat : {e}")

# --- 4) Événements ---
@bot.event
async def on_ready():
    print(f"✅ {bot.user} est en ligne !")
    print("🔧 Commandes chargées :", [c.name for c in bot.commands])
    if not heartbeat.is_running():
        heartbeat.start()

@bot.event
async def on_disconnect():
    print("⚠️ Déconnecté de Discord…")

@bot.event
async def on_resumed():
    print("🔄 Reconnecté à Discord.")

# XP texte + log général
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    add_xp(message.author.id, 10)
    await maybe_level_up(message.author)
    log_ch = bot.get_channel(LOGS_CHANNEL_ID)
    if log_ch:
        xp = get_xp(message.author.id)
        await log_ch.send(f"✉️ {message.author.mention} a gagné 10 XP (texte). Total: {xp} XP.")
    await bot.process_commands(message)

# XP vocal + log général
@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel is None and after.channel:
        set_voice_join(member.id, int(time.time()))
    elif before.channel and after.channel != before.channel:
        t0 = pop_voice_join(member.id)
        if t0:
            duration = int(time.time()) - t0
            xp_gain = duration // 60
            add_xp(member.id, xp_gain)
            await maybe_level_up(member)
            log_ch = bot.get_channel(LOGS_CHANNEL_ID)
            if log_ch:
                total = get_xp(member.id)
                await log_ch.send(f"🔊 {member.mention} a gagné {xp_gain} XP (voix). Total: {total} XP.")

@bot.event
async def on_member_join(member):
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        await ch.send(f"🎮 Bienvenue {member.mention} ! Tu as reçu **ZAKS Rookie** 👶")
    role = discord.utils.get(member.guild.roles, name="ZAKS Rookie")
    if role:
        try:
            await member.add_roles(role)
        except:
            pass

@bot.event
async def on_member_remove(member):
    ch = bot.get_channel(LOGS_CHANNEL_ID)
    if ch:
        await ch.send(f"🚪 {member} a quitté.")

# --- Commande !level (salon dédié) ---
@bot.command(name="level")
async def level_cmd(ctx, member: discord.Member=None):
    # accessible uniquement dans salon LEVEL_LOG_CHANNEL_ID
    if ctx.channel.id != LEVEL_LOG_CHANNEL_ID:
        return
    member = member or ctx.author
    xp = get_xp(member.id)
    lvl = xp_to_level(xp)
    current_threshold = max([t for t in LEVEL_ROLES if t <= xp])
    next_thresholds = [t for t in LEVEL_ROLES if t > xp]
    if next_thresholds:
        next_t = min(next_thresholds)
        next_role = LEVEL_ROLES[next_t]
        next_info = f"Il te manque {next_t - xp} XP pour devenir **{next_role}**."
    else:
        next_info = "Tu as atteint le niveau max !"
    embed = discord.Embed(title="🎚 Progression", color=discord.Color.blurple())
    embed.set_author(name=member.display_name, icon_url=member.avatar.url if member.avatar else None)
    embed.add_field(name="XP actuelle", value=f"{xp}", inline=True)
    embed.add_field(name="Niveau", value=f"{lvl} / 100", inline=True)
    embed.add_field(name="Prochain palier", value=next_info, inline=False)
    embed.set_footer(text=f"{min(xp, MAX_XP)}/{MAX_XP} XP")
    await ctx.send(embed=embed)

# --- Commandes Admin: levelup & leveldown ---
@commands.has_role('Admin')
@bot.command(name="levelup")
async def levelup_cmd(ctx, member: discord.Member=None, amount: int=1):
    member = member or ctx.author
    add_xp(member.id, amount)
    await maybe_level_up(member)
    new_xp = get_xp(member.id)
    await ctx.send(f"✅ {amount} XP ajouté à {member.mention}. XP actuel: {new_xp}")

@commands.has_role('Admin')
@bot.command(name="leveldown")
async def leveldown_cmd(ctx, member: discord.Member=None, amount: int=1):
    member = member or ctx.author
    current = get_xp(member.id)
    sub = min(amount, current)
    set_xp(member.id, current - sub)
    await maybe_level_up(member)
    new_xp = get_xp(member.id)
    await ctx.send(f"❌ {sub} XP retiré à {member.mention}. XP actuel: {new_xp}")

# --- Commande Admin: clearall ---
@commands.has_role('Admin')
@bot.command(name="clearall")
async def clearall_cmd(ctx):
    deleted = await ctx.channel.purge()
    log_ch = bot.get_channel(LOGS_CHANNEL_ID)
    if log_ch:
        await log_ch.send(f"🧹 {len(deleted)} messages supprimés dans {ctx.channel.mention}.")

# --- 5) Lancement ---
def run_bot():
    print("🚀 Tentative connexion…")
    try:
        bot.run(os.environ['TOKEN_BOT_DISCORD'], reconnect=True)
    except KeyError:
        print("❌ TOKEN_BOT_DISCORD manquant !")
    except discord.LoginFailure:
        print("❌ Token invalide !")
    except Exception as e:
        print(f"❌ Crash inattendu : {e}")

if __name__ == "__main__":
    while True:
        run_bot()
        print("⏳ Reconnexion dans 5s…")
        time.sleep(5)
