from config import TOKEN
from state import bot

import helpers.core
import tasks.lifecycle
import commands.channels
import commands.help_prices
import commands.register
import commands.delete
import commands.months
import commands.specialties
import commands.prefix_register
import views.paginators
import commands.reports
import commands.admin

from tasks.lifecycle import custom_setup

bot.setup_hook = custom_setup
bot.run(TOKEN)
