import os
import time
import threading
import sqlite3

import discord
from discord import app_commands
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

# --- Fonctions utilitaires ---
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

# --- XP / Niveau ---
MAX_XP = 10000

def xp_to_level(xp: int) -> int:
    lvl = int(xp * 99 / MAX_XP) + 1
    return min(max(lvl, 1), 100)

LEVEL_ROLES = {0: "ZAKS Rookie", 1000: "ZAKS Gamers", 5000: "ZAKS Elite"}

async def maybe_level_up(member: discord.Member):
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
            log_ch = bot.get_channel(LOGS_CHANNEL_ID)
            if log_ch:
                await log_ch.send(f"🏅 {member.mention} est maintenant **{role_name}** ({xp} XP) !")
        except Exception:
            pass

# --- 1) Flask (Render keep-alive) ---
app = Flask(__name__)
@app.route('/')
def home():
    return "ZAKS BOT est en ligne !"
def run_flask():
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host='0.0.0.0', port=8080)
threading.Thread(target=run_flask).start()

# --- 2) Bot Discord & slash tree ---
GUILD_ID = 123456789012345678  # <- remplace par ton ID serveur
GUILD = discord.Object(id=GUILD_ID)

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)
tree = bot.tree

WELCOME_CHANNEL_ID = 1302027297116917922
LOGS_CHANNEL_ID = 1400141141663547462
LEVEL_LOG_CHANNEL_ID = 1401528018345787462

# --- 3) Heartbeat + Ready ---
@tasks.loop(minutes=5)
async def heartbeat():
    await bot.change_presence(status=discord.Status.online, activity=discord.Game('ZAKS BOT'))

@bot.event
async def on_ready():
    # Sync slash commands to the guild for immediate availability
    synced = await tree.sync(guild=GUILD)
    print(f"✅ {bot.user} en ligne ! Commands synced to guild {GUILD_ID}: {[c.name for c in synced]}")
    if not heartbeat.is_running():
        heartbeat.start()

# --- 4) Logs XP texte & vocal ---
@bot.event
async def on_message(message):
    if message.author.bot: return
    add_xp(message.author.id, 10)
    await maybe_level_up(message.author)
    log_ch = bot.get_channel(LOGS_CHANNEL_ID)
    if log_ch:
        xp = get_xp(message.author.id)
        await log_ch.send(f"✉️ {message.author.mention} a gagné 10 XP (texte). Total: {xp} XP.")
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel is None and after.channel:
        set_voice_join(member.id, int(time.time()))
    elif before.channel != after.channel:
        t0 = pop_voice_join(member.id)
        if t0:
            xp_gain = (int(time.time()) - t0) // 60
            add_xp(member.id, xp_gain)
            await maybe_level_up(member)
            log_ch = bot.get_channel(LOGS_CHANNEL_ID)
            if log_ch:
                total = get_xp(member.id)
                await log_ch.send(f"🔊 {member.mention} a gagné {xp_gain} XP (voix). Total: {total} XP.")

# --- 5) Slash commands ---
@tree.command(guild=GUILD, name='level', description='Affiche ton XP et ton niveau')
async def slash_level(interaction: discord.Interaction):
    if interaction.channel.id != LEVEL_LOG_CHANNEL_ID:
        await interaction.response.send_message(f"❌ Utilise /level dans <#{LEVEL_LOG_CHANNEL_ID}>.", ephemeral=True)
        log = bot.get_channel(LOGS_CHANNEL_ID)
        if log: await log.send(f"⚠️ {interaction.user.mention} a tenté /level dans <#{interaction.channel.id}>")
        return
    xp = get_xp(interaction.user.id); lvl = xp_to_level(xp)
    next_levels = [t for t in sorted(LEVEL_ROLES) if t > xp]
    next_info = f"Il te manque {next_levels[0]-xp} XP pour **{LEVEL_ROLES[next_levels[0]]}**." if next_levels else 'Niveau max atteint !'
    embed = discord.Embed(title='🎚 Progression', color=discord.Color.blurple())
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    embed.add_field(name='XP actuelle', value=str(xp), inline=True)
    embed.add_field(name='Niveau', value=f"{lvl} / 100", inline=True)
    embed.add_field(name='Prochain palier', value=next_info, inline=False)
    embed.set_footer(text=f"{min(xp, MAX_XP)}/{MAX_XP} XP")
    await interaction.response.send_message(embed=embed)
    log = bot.get_channel(LOGS_CHANNEL_ID)
    if log: await log.send(f"🔍 {interaction.user.mention} a utilisé /level dans <#{interaction.channel.id}>")

@tree.command(guild=GUILD, name='levelup', description="Ajoute de l'XP à un membre")
@app_commands.describe(member='Membre cible', amount="Quantité d'XP")
async def slash_levelup(interaction: discord.Interaction, member: discord.Member=None, amount: int=1):
    if 'Admin' not in [r.name for r in interaction.user.roles]:
        return await interaction.response.send_message('❌ Permission refusée.', ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    target = member or interaction.user
    add_xp(target.id, amount)
    await maybe_level_up(target)
    new_xp = get_xp(target.id)
    log = bot.get_channel(LOGS_CHANNEL_ID)
    if log: await log.send(f"✅ {interaction.user.mention} a utilisé /levelup sur {target.mention} (+{amount}) dans <#{interaction.channel.id}>")
    await interaction.followup.send(f"✅ {amount} XP ajouté à {target.mention}. Total: {new_xp} XP.", ephemeral=True)

@tree.command(guild=GUILD, name='leveldown', description="Retire de l'XP à un membre")
@app_commands.describe(member='Membre cible', amount="Quantité d'XP")
async def slash_leveldown(interaction: discord.Interaction, member: discord.Member=None, amount: int=1):
    if 'Admin' not in [r.name for r in interaction.user.roles]:
        return await interaction.response.send_message('❌ Permission refusée.', ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    target = member or interaction.user
    cur = get_xp(target.id); sub = min(amount, cur)
    set_xp(target.id, cur - sub); await maybe_level_up(target)
    new_xp = get_xp(target.id)
    log = bot.get_channel(LOGS_CHANNEL_ID)
    if log: await log.send(f"❌ {interaction.user.mention} a utilisé /leveldown sur {target.mention} (-{sub}) dans <#{interaction.channel.id}>")
    await interaction.followup.send(f"❌ {sub} XP retiré à {target.mention}. Total: {new_xp} XP.", ephemeral=True)

@tree.command(guild=GUILD, name='clearall', description='Supprime tous les messages du salon')
async def slash_clearall(interaction: discord.Interaction):
    if 'Admin' not in [r.name for r in interaction.user.roles]:
        return await interaction.response.send_message('❌ Permission refusée.', ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge()
    log = bot.get_channel(LOGS_CHANNEL_ID)
    if log: await log.send(f"🧹 {interaction.user.mention} a utilisé /clearall dans <#{interaction.channel.id}> — {len(deleted)} messages supprimés.")
    await interaction.followup.send(f"🧹 {len(deleted)} messages supprimés.", ephemeral=True)

# --- 6) Lancement ---
def run_bot():
    bot.run(os.environ['TOKEN_BOT_DISCORD'], reconnect=True)

if __name__ == '__main__':
    run_bot()
