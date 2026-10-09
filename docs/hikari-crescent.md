"# Welcome to Crescent[#](#welcome-to-crescent ""Permanent link"")

[!](https://github.com/hikari-crescent/crescent-chan)

Crescent is a command handler for [Hikari](https://github.com/hikari-py/hikari) that keeps your projects neat and tidy! It is designed from the ground up to function with application commands in a type safe manner. You won't run into silly bugs when using Crescent!
Take a look at [the crescent template](https://github.com/magpie-dev/crescent-template) to see how your code will look when using Crescent.

## Installation[#](#installation ""Permanent link"")

`hikari-crescent` supports Python 3.9 and newer.

```
pip install hikari-crescent
```

## Resources[#](#resources ""Permanent link"")

-   [Pypi](https://pypi.org/project/hikari-crescent/)

-   [Github](https://github.com/hikari-crescent/hikari-crescent)

-   [Getting Started](getting_started)

-   [Guides](guides)


## Acknowledgements[#](#acknowledgements ""Permanent link"")

Thank you to [@hypergonial](https://github.com/Hypergonial) for help with setting up the docs."
"# Installation[#](#installation ""Permanent link"")

`hikari-crescent` supports Python 3.9 and newer.

```
pip install hikari-crescent
```

# Creating a Bot Application[#](#creating-a-bot-application ""Permanent link"")

Before you can start programming, you need to create a discord bot application.

-   **Create a Bot Application**

    ---

    -   Navigate to [The Discord Application Portal](https://discord.com/developers/applications), then click on the blue button that says ""New Application"".

    ![New Application](../resources/new_application.png)

    -   Click on the ""Bot"" button.

    ![Bot Button](../resources/bot_button.png)

    -   Click on the blue ""Add Bot"" button, and pick a memorable name!

        !


    ---

    **Finding your token** (For rest bots)

    ---

    Navigate to the bot page. Press the ""Reset Token"" button to claim your token. You may need to enter a authentication code. Write this down and don't share it to anybody. It will give them access to your bot!

    !

-   **Invite the Bot**

    ---

    -   Navigate to the oauth2 url generator.

    !

    -   Select the bot scope.

    !

    -   Scroll farther down to the bottom of the page. Press the copy button.

    !

    Paste this URL into your web browser. You will get an invite page for your bot. Add the bot to a server you are going to develop it on.

    !


> [!NOTE]
> Note
>
> Setting up a REST bot on the discord developer portal is very complicated, so this guide does not cover that. Please read the Discord documentation if you want to use a REST bot.

## Basics[#](#basics ""Permanent link"")

Copy this code into a python file, and run with `python filename.py`.

GatewayREST

```
import crescent
import hikari

bot = hikari.GatewayBot(""YOUR_TOKEN"")
client = crescent.Client(bot)

@client.include
@crescent.command(name=""say"")
class Say:
    word = crescent.option(str, ""The word to say"")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.respond(self.word)

bot.run()
```

```
import crescent
import hikari

bot = hikari.RESTBot(""YOUR_TOKEN"")
client = crescent.Client(bot)

@client.include
@crescent.command(name=""say"")
class Say:
    word = crescent.option(str, ""The word to say"")

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.respond(self.word)

bot.run()
```

## Tooling[#](#tooling ""Permanent link"")

It is recommended to use a typechecker when working with crescent. Both the [Mypy](https://github.com/python/mypy) and [Pyright](https://github.com/microsoft/pyright) typecheckers are supported. The developer recommends pyright if you don't know what to pick.

> [!WARNING]
> Warning
>
> Crescent does not throw exceptions for issues a typechecker would catch. Use a typechecker.

## Next Steps[#](#next-steps ""Permanent link"")

🎉 Congratulations! At this point you should have a bot. Now you should check out the [guides](../guides), or if want to jump straight into coding, check out the [template project](https://github.com/hikari-crescent/template) for some quick examples."
"# Crescent API reference[#](#crescent-api-reference ""Permanent link"")

Welcome to the `hikari-crescent` API documentation. If you are new to Crescent, first take a look at [guides](../guides/)."
"# Guides

Heres a bunch of guides for things you'll find useful! Please make a Github issue if you find any errors.

-   [**/ Commands**](commands)

    ---

    The fundamentals for creating slash commands with crescent, and everything past the fundamentals.

-   [**Plugins**](plugins)

    ---

    Plugins are used to split your bot into multiple files.

-   [**Events**](events)

    ---

    Guides on how to to subscribe to events sent to your bot by Discord.

-   [**Hooks**](hooks)

    ---

    Hooks are a powerful tool allowing you to run code before an after a command. Hooks can be used for command setup and cleanup code.

-   [**Error Handling**](error_handling)

    ---

    Crescent provides powerful tools for error handling, giving you control even when things go wrong.

-   [**Cooldowns**](ext/cooldowns)

    ---

    Command rate-limiting tools built into Crescent. These tools allow you to give commands a cooldown for when they can be used.

-   [**Tasks**](ext/tasks)

    ---

    Tools to loop functions on a specific time interval. Tasks automatically start and stop when the bot starts and stops.

-   [**Locales**](ext/locales)

    ---

    Locales are used to localize your bot for different languages."
"# Hooks[#](#hooks ""Permanent link"")

Hooks allow you to run code before or after a command is run or an event is processed. They also allow you to create checks for a certain command.

This is a simple command hook that says ""hello there"" before every command you hook it to.

```
async def my_hook(ctx: crescent.Context) -> None:
    await ctx.respond(""Hello there"")
```

To use this hook on a command, simply do:

```
@client.include
@crescent.hook(my_hook)
@crescent.command
async def my_command(ctx: crescent.Context) -> None:
    await ctx.respond(""General Kenobi"")
```

This command will respond ""Hello there"" and ""General kenobi"" in two different messages.

You can access command options in hooks with `ctx.options`. This is a dict of option name to option value.

## Using hooks as checks[#](#using-hooks-as-checks ""Permanent link"")

You can also stop a command callback from running in a hook. Simply return `crescent.HookResult(exit=True)`

This is a command that uses that feature. It stops you from using the command if your name has an ""L"" in it.

```
async def no_Ls_allowed(ctx: crescent.Context) -> crescent.HookResult:
    if ""l"" in ctx.user.username.lower():
        await ctx.respond(""You can't use this command!"")
        return crescent.HookResult(exit=True)

    return crescent.HookResult()

@client.include
@crescent.hook(no_Ls_allowed)
@crescent.command
async def my_command(ctx: crescent.Context) -> None:
    await ctx.respond(""Hello"")
```

## Running a hook after a command[#](#running-a-hook-after-a-command ""Permanent link"")

To run a hook after a command, add `after=True` to the decorator. This command will return ""General Kenobi"" then ""Hello there"" in two separate messages.

```
async def my_hook(ctx: crescent.Context) -> None:
    await ctx.respond(""Hello there"")
```

To use this hook on a command, simply do:

```
@client.include
@crescent.hook(my_hook, after=True)
@crescent.command
async def my_command(ctx: crescent.Context) -> None:
    await ctx.respond(""General Kenobi"")
```

## Adding hooks to more than commands[#](#adding-hooks-to-more-than-commands ""Permanent link"")

Bots and plugins (we will cover these later) support hooks by adding them with the `command_hooks` and `command_after_hooks` kwargs. Hooks on the bot object will run for all commands. Hooks on the plugin object will run for all commands in that plugin.

```
bot = crescent.Bot(""..."", command_hooks=[hook_a, hook_b])
```

`crescent.Group` and `crescent.SubGroup` also support hooks. Use the `hooks` and `after_hooks` kwargs to add them. Groups and sub groups will add hooks to any commands in their respective groups.

```
group = crescent.Group(""group"", hooks=[hook_a])
sub_group = group.sub_group(""sub-group"", hooks=[hook_b])
```

Sub groups will inherit all hooks from the group.

### Hook Resolution Order[#](#hook-resolution-order ""Permanent link"")

`Command -> Sub Group -> Group -> Plugin -> Bot`

## Using hooks for ratelimiting[#](#using-hooks-for-ratelimiting ""Permanent link"")

One of crescent's built in extensions is `crescent.ext.cooldowns`, allowing for rate limiting. To use this extension, you must install `hikari-crescent[cooldowns]`.

```
import crescent
import datetime
from crescent.ext import cooldowns

bucket_size = 1
delay = datetime.timedelta(seconds=20)

@client.include
@crescent.hook(cooldowns.cooldown(bucket_size, delay))
@crescent.command
async def my_command(ctx: crescent.Context) -> None:
    await ctx.respond(""General Kenobi"")
```

To see more information on this function, check the API reference for `crescent.ext.cooldowns`.

## Event Hooks[#](#event-hooks ""Permanent link"")

Hooks can be used for events. An event callback can use any hook for the event type or supertype of the event type in the callback.

```
async def human_only(event: hikari.MessageCreateEvent) -> crescent.HookResult:
    if not event.is_human:
        return crescent.HookResult(exit=True)
    return crescent.HookResult()

@client.include
@crescent.hook(human_only)
@crescent.event
async def on_message(event: hikari.MessageCreateEvent):
    print(""Received an event from a human."")
```

Similar to command hooks, `HookResult` can be used to exit early from a function in a event hook. After hooks can also be used."
"# Error Handling[#](#error-handling ""Permanent link"")

The only thing exceptional is your code never throwing exceptions. Crescent provides error handling features for commands, events, and autocomplete to solve this problem.

Error handles can be registered for a specific exception. Creating a custom exception type for when things are supposed to go wrong gives you a lot of control over your program.

This error will be handled with the [`@crescent.catch_command`](../../api_reference/errors/#crescent.errors.catch_command ""<code class=\""doc-symbol doc-symbol-heading doc-symbol-function\""></code>            <span class=\""doc doc-object-name doc-function-name\"">catch_command</span>"") decorator. This function takes an exception and [`crescent.Context`](../../api_reference/context/#crescent.context.Context ""<code class=\""doc-symbol doc-symbol-heading doc-symbol-class\""></code>            <span class=\""doc doc-object-name doc-class-name\"">Context</span>
<span class=\""doc doc-labels\"">
<small class=\""doc doc-label doc-label-dataclass\""><code>dataclass</code></small>
</span>"") as an argument. All subclasses of the exception will be caught.

```
# Creating a new error class gives more control over what errors are handled.
class MyError(Exception):
  ...

@client.include
@crescent.command
async def my_command(ctx: crescent.Context, number: int):
  # Lets raise an error if the number wasn't positive.
  if number < 0:
    raise MyError
  await ctx.reply(str(number))

# Handle the error
@client.include
@crescent.catch_command(MyError)
# The name of this function does not matter.
async def on_cmd_my_error(exc: MyError, ctx: crescent.Context) -> None:
    await ctx.respond(f""{exc} raised in {ctx.command}!"")
```

Event and autocomplete error handling works similar to command error handling.

```
@client.include
@crescent.catch_event(MyError)
async def on_event_random_error(exc: MyError, event: hikari.Event) -> None:
    # In this example, we don't respond to the event if something went wrong.
    print(f""{exc} raised in {event}!"")

@client.include
@crescent.catch_autocomplete(MyError)
async def on_autocomplete_random_error(
    exc: MyError,
    ctx: crescent.AutocompleteContext,
    inter: hikari.AutocompleteInteractionOption,
) -> None:
    print(f""{exc} raised in autocomplete for {ctx.command}!"")
```

Note that error handling can catch errors from other plugins. If you want to catch an error specific to a plugin the best method to do this is creating a new exception type, only referenced in that plugin.

## Handling All Exceptions[#](#handling-all-exceptions ""Permanent link"")

A global error handler can be created by catch [`Exception`](https://docs.python.org/3.9/library/exceptions.html#Exception).

```
@client.include
@crescent.catch_command(Exception)
async def global_error_handler(exc: Exception, ctx: crescent.Context):
    await ctx.respond(""handled"")
```

The same method can be used with event error handlers and autocomplete error handlers."
"# Plugins[#](#plugins ""Permanent link"")

Plugins are used to split your bot into multiple files. Plugins require your bot to be packaged, so it is recommended to follow this structure. You can see an example of this structure in the [crescent template](https://github.com/hikari-crescent/template).

```
working_directory/
    bot/
        __main__.py
        plugins/
            plugin_a.py
            plugin_b.py
```

The `__main__.py` file is where you create your client. It would look something like this:

```
import crescent
import hikari

bot = hikari.GatewayBot(""YOUR_TOKEN_HERE"")
client = crescent.Client(bot)

bot.run()
```

Now to load plugins, simply use the `bot.plugins.load_folder` function.

```
bot = hikari.GatewayBot(""YOUR_TOKEN_HERE"")
client = crescent.Client(bot)

client.plugins.load_folder(""bot.plugins"")

bot.run()
```

When you run your bot with `python -m bot` from `working_directory`, plugins will be loaded on startup.

> [!NOTE]
> Note
>
> The path that is used to load plugins is relative to the directory you are running the bot from.

## Inside a plugin file[#](#inside-a-plugin-file ""Permanent link"")

In the inside of your plugin file you create a plugin class. You can use `@plugin.include` to add a command to your bot exactly the same way you would with `@bot.include`. The `plugin` variable must be called `plugin`.

```
plugin = crescent.Plugin[hikari.GatewayBot, None]()

@plugin.include
@crescent.command
class plugin_command:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.respond(""Inside a plugin"")
```

If you need to access your bot class inside a plugin file, you can use the `plugin.app` attribute. Accessing this attribute will raise an exception if the plugin is not yet loaded.

```
plugin = crescent.Plugin[hikari.GatewayBot, None]()

@plugin.include
@crescent.command
class plugin_command:
    async def callback(self, ctx: crescent.Context) -> None:
        print(plugin.app)  # <crescent.bot.Bot object at 0x????????????>
        ...
```

## Hooks[#](#hooks ""Permanent link"")

Plugins allow you run to run functions when they are loaded and unloaded.

```
plugin = crescent.Plugin[hikari.GatewayBot, None]()

@plugin.load_hook
def load():
    print(""The plugin is loaded"")

@plugin.unload_hook
def unload():
    print(""The plugin is unloaded"")
```

## Type Safe `plugin.app`[#](#type-safe-pluginapp ""Permanent link"")

If you are using a inherited bot class you can change generics on `crescent.Plugin` so `plugin.app` is typed with your class.

```
import typing

class MyBot(hikari.GatewayBot):
    ...

MyPlugin = crescent.Plugin[MyBot, None]

typing.reveal_type(MyPlugin().app)  # `MyBot`
```

## Sharing State Between Plugins[#](#sharing-state-between-plugins ""Permanent link"")

Sharing objects between different files is hard, Crescent provides the `model` attribute on plugins to solve this problem. A `model` is any object you want that will be injected into your plugins.

The `model` does the same role as dependency injection in [hikari-arc](https://github.com/hypergonial/hikari-arc) and [hikari-tanjun](https://github.com/FasterSpeeding/Tanjun).

```
import dataclasses
import hikari
import crescent

# The example model is a dataclass. This class can be whatever you want.
@dataclasses.dataclass
class Model:
    value = 5

bot = hikari.GatewayBot(""TOKEN"")
client = crescent.Client(bot, Model())
```

You should also update your plugin type alias to use the model you created.

```
Plugin = crescent.Plugin[hikari.GatewayBot, Model]
```

After the plugin is loaded, you can access your model with the `model` property.

```
# The plugin option created in the previous code block.
plugin = Plugin()

# A function that is run when the plugin is loaded. The antithesis, `plugin.unload_hook`, also exists.
@plugin.load_hook
def on_load():
    print(plugin.model)
```

### Tips and Tricks[#](#tips-and-tricks ""Permanent link"")

-   Objects That Need to be Created in an Async Function

    Its common to have objects that need to be instantiated in an async function. The easiest way to do this is subscribing a method on your model to `hikari.StartingEvent`.

    ```
    class Model:
        def __init__(self) -> None:
            self._db: Database | None = None

        async def on_start(self, _: hikari.StartedEvent) -> None:
            self._db = await Database.create()

        @property
        def db(self) -> Database:
            assert self._db
            return self._db

    model = Model()

    bot = hikari.GatewayBot(""TOKEN"")
    client = crescent.Client(bot, model)

    bot.event_manager.subscribe(hikari.StartedEvent, model.on_start)

    bot.run()
    ```"
"# Cooldowns[#](#cooldowns ""Permanent link"")

This module allows you to rate limit users with a sliding window rate limit.

The `crescent.ext.cooldowns` module provides a hook.

-   `capacity` is the amount of times the command can be used in a timeframe.
-   `period` is the length of this timeframe.

```
import crescent
import datetime
from crescent.ext import cooldowns

@client.include
# This command be used 3 times in 20 seconds.
@crescent.hook(cooldowns.cooldown(capacity=3, period=datetime.timedelta(seconds=20)))
@crescent.command
async def cooldowned(ctx: crescent.Context):
    print(""Doing expensive operation..."")
    await ctx.respond(""Hello!"")
```

## Rate Limited Hook[#](#rate-limited-hook ""Permanent link"")

Callbacks can be set to run when a user is ratelimited.

```
async def on_rate_limited(ctx: crescent.Context, time_remaining: datetime.timedelta) -> None:
    await ctx.respond(f""You are ratelimited for {time_remaining.total_seconds()}s."")

@client.include
@crescent.hook(
    cooldowns.cooldown(1, datetime.timedelta(minutes=1), callback=on_rate_limited),
)
@crescent.command
async def cooldowned(ctx: crescent.Context) -> None:
    print(""Doing expensive operation..."")
    await ctx.respond(""Hello!"")
```

## Custom Bucket[#](#custom-bucket ""Permanent link"")

The default bucket uses user IDs to separate users.

This is how the default bucket is implemented:

```
import typing
import crescent

def default_bucket(ctx: crescent.Context) -> typing.Any:
    return ctx.user.id
```

This is a bucket that rate limits users based on ID and guild ID:

```
import crescent
import typing

def custom_bucket(ctx: crescent.Context) -> typing.Any:
    return f""{ctx.guild_id}{ctx.user.id}""
```

To use a custom bucket, pass it into the `bucket` kwarg.

```
@client.include
@crescent.hook(cooldowns.cooldown(3, datetime.timedelta(seconds=20), bucket=custom_bucket))
@crescent.command
async def cooldowned(ctx: crescent.Context):
    print(""Doing expensive operation..."")
    await ctx.respond(""Hello!"")
```"
"# Events[#](#events ""Permanent link"")

Events are the main driving force behind Gateway bots. Whenever ""something"" happens on Discord that your bot should be notified of, Discord will send an event.

Although hikari provides `hikari.GatewayBot.subscribe` you should NOT use this function. Crescent's method of subscribing to events will work in plugins and will allow you to take advantage of [error handling](../error_handling).

The `@crescent.event` decorator is used to subscribe to an event. The type hint for `event` is the event type from hikari you want to subscribe to. This must be a subtype of [`hikari.Event`](https://docs.hikari-py.dev/en/latest/reference/hikari/events/base_events/#hikari.events.base_events.Event).

```
import hikari

@client.include
@crescent.event
async def on_message_create(event: hikari.MessageCreateEvent):
    if event.message.author.is_bot:
        return
    await event.message.respond(""Hello!"")
```"
"# Tasks[#](#tasks ""Permanent link"")

This module allows you to loop functions on a certain time period.

## Loops[#](#loops ""Permanent link"")

Loops run a certain time period after you start the bot.

Using kwargs, functions can be set to loop after a certain amount of hours, minutes, or seconds.

```
from crescent.ext import tasks
from datetime import datetime

# This function runs once every minute.
@client.include
@tasks.loop(hours=0, minutes=1, seconds=0)
async def loop():
    print(datetime.now())
```

A `datetime.timedelta` object can be passed in to `tasks.loop` for more control over when the function loops.

```
from crescent.ext import tasks
from datetime import datetime, timedelta

# This function runs once every day.
@client.include
@tasks.loop(timedelta(days=1))
async def loop():
    print(datetime.now())
```

## Cronjobs[#](#cronjobs ""Permanent link"")

Cronjobs are supported with the `tasks.cronjob` function. [crontab.guru](https://crontab.guru/) is useful for writing cron expressions.

> [!INFO]
> Info
>
> The library [croniter](https://pypi.org/project/croniter/) is used for parsing cron expressions.

```
from crescent.ext import tasks
from datetime import datetime

# This function runs once every minute.
@client.include
@tasks.cronjob(""* * * * *"")
async def loop():
    print(datetime.now())
```

The `on_startup=True` can be set to force the function to run when the bot is started.

```
@client.include
@tasks.cronjob(""* * * * *"", on_startup=True)
async def loop():
    print(datetime.now())
```"
"# Commands[#](#commands ""Permanent link"")

Before you can create a command, you need to create a bot.

GatewayREST

```
import crescent
import hikari

bot = hikari.GatewayBot(""YOUR_TOKEN"")
client = crescent.Client(bot)

# `bot.run()` starts the bot.
# Any code after this line will not be run until the bot is closed.
bot.run()
```

```
import crescent
import hikari

bot = hikari.RESTBot(""YOUR_TOKEN"")
client = crescent.Client(bot)

# `bot.run()` starts the bot.
# Any code after this line will not be run until the bot is closed.
bot.run()
```

> [!WARNING]
> Warning
>
> Storing your token in your source code is a bad idea. Store your TOKEN in a `.env` file.

The first command we will make is the ping command.

GatewayREST

```
bot = hikari.GatewayBot(""YOUR_TOKEN"")
client = crescent.Client(bot)

# Commands can be defined after you create the client variable
# and before `bot.run()`

@client.include
@crescent.command(name=""ping"", description=""Ping the bot."")
class PingCommand:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.respond(""Pong!"")

bot.run()
```

```
bot = hikari.RESTBot(""YOUR_TOKEN"")
client = crescent.Client(bot)

# Commands can be defined after you create the client variable
# and before `bot.run()`

@client.include
@crescent.command(name=""ping"", description=""Ping the bot."")
class PingCommand:
    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.respond(""Pong!"")

bot.run()
```

> ⚠️ Commands must call `await ctx.respond()` within 3 seconds or call `await ctx.defer()` to get 15 minutes to respond.

So what's going on here? `@crescent.command` turns your class into a command object. `@bot.include` adds the command to your bot. Many objects in Crescent can be added to your bot with `@bot.include`, these are called Includables and we will go over them in more detail later.

If you are new to Python, you may not have seen `ctx: crescent.Context` before. This is called a type hint. It tells the reader what type `ctx` is, and your IDE can use type hints to provide better autocomplete. Although they are not required, it is recommended to use type hints whenever you can.

```
#      The name of the argument   The return type
#                 \/                    \/
def my_function(argument: SomeType) -> None:
#                           /\
#                The type of the argument
#
# The argument name and argument type
# are separated with a colon.
```

### Adding Options[#](#adding-options ""Permanent link"")

Options are added by adding class-attrs to the class.

```
@client.include
@crescent.command(name=""say"")
class SayCommand:
# The name of the command option
#    \/
    word = crescent.option(str)
#                           /\
# The type of the command option

    async def callback(self, ctx: crescent.Context) -> None:
        # options are accessed attributes on the class
        await ctx.respond(self.word)
```

Crescent's option syntax is type safe. This means that commands will seamlessly work with typecheckers like mypy and pyright. (You don't need to worry about this if you are new to Python!)

Class commands can be cumbersome for small commands. Crescent provides function commands for those cases.

```
@client.include
@crescent.command
async def ping(ctx: crescent.Context):
    await ctx.respond(""Pong!"")
```

It is recommended to use function commands when your command does not have any options.

## User and Message commands[#](#user-and-message-commands ""Permanent link"")

So far only slash commands have been covered. There is two more types of application commands: user context menu and message context menu commands. You can use these by right clicking on a user or message respectively.

Both user and message commands are only supported as functions.

```
@bot.include
@crescent.user_command
async def user_command(ctx: crescent.Context, user: hikari.User):
    ...

@bot.include
@crescent.message_command
async def message_command(ctx: crescent.Context, message: hikari.Message):
    ...
```

## Command Options[#](#command-options ""Permanent link"")

This is what a command with an option called `name` looks like in the Discord client..

![Example of what name option looks like](../../resources/name_option.png)

Options can also have a custom description and name. If no description is provided, the description will default to ""No Description"". This example shows an option amed ""option"" with the description ""your custom description"". The secondoption, `option2`, has the name ""custom-name"" and description ""also your custom description"".

```
@client.include
@crescent.command
class MyCommand:
    option = crescent.option(str, ""your custom description"")
    option2 = crescent.option(str, name=""custom-name"", description=""also your custom description"")

    async def callback(self, ctx: crescent.Context) -> None:
        ...

    # The `...` is a placeholder that means that your code
    # should go there instead.
```

## Option Types[#](#option-types ""Permanent link"")

Crescent provides these option types. You can find more information on option types [here](https://discord.com/developers/docs/interactions/application-commands#application-command-object-application-command-option-type) (You can ignore `SUBCOMMAND` and `SUBCOMMAND_GROUP` for now.) This might look a bit daunting, but we will go into detail on what each option type is in this section.

| Type | Option Type |
| --- | --- |
| str | Text |
| int | Integer |
| bool | Boolean |
| float | Number |
| hikari.User | User |
| hikari.Role | Role |
| crescent.Mentionable | Role or User |
| hikari.PartialChannel | Channel. The options will be the channel type and its subclasses. |
| list[hikari.PartialChannel] | Channel. ^ |
| hikari.Attachment | Attachment |

### Making Parameters Optional[#](#making-parameters-optional ""Permanent link"")

Options will be optional if a default value is provided. This example shows an option with the default value `None`.

```
@client.include
@crescent.command(name=""command"")
class MyCommand:
    optional_option = crescent.option(str, default=None)

    async def callback(self, ctx: crescent.Context) -> None:
        ...
```

### More Information on Types[#](#more-information-on-types ""Permanent link"")

Strings, Ints, Floats, and Booleans all use python's built in types.

> [!NOTE]
> Note
>
> If you are comfortable reading function overloads you can look at [the source code](https://github.com/hikari-crescent/hikari-crescent/blob/main/crescent/commands/options.py#L174).

```
@client.include
@crescent.command(name=""command"")
class MyCommand:
    word = crescent.option(str)
    integer = crescent.option(int)
    number = crescent.option(float)
    boolean = crescent.option(bool)

    async def callback(self, ctx: crescent.Context) -> None:
        # You can now do something with the options.
        await ctx.respond(
            f""{self.word}\n{self.integer}\n{self.number}\n{self.boolean}""
        )
```

These types use a hikari object.

```
import hikari

@client.include
@crescent.command(name=""command"")
class MyCommand:
    user = crescent.option(hikari.User)
    role = crescent.option(hikari.Role)
    attachment = crescent.option(hikari.Attachment)

    # The channel type will be restricted depending on what
    # channel object you choose. In this example only channels
    # that users can type in can be chosen.
    channel = crescent.option(hikari.TextableChannel)

    # This option can only be voice channels.
    voice_channel = crescent.option(hikari.GuildVoiceChannel)

    async def callback(self, ctx: crescent.Context) -> None:
        ...
```

The final option type is mentionable, which allows a user to choose a user or role.

```
import hikari

@client.include
@crescent.command(name=""command"")
class MyCommand:
    mentionable = crescent.option(crescent.Mentionable)

    async def callback(self, ctx: crescent.Context) -> None:
        if self.mentionable.user:
            # This is a user. `mentionable.role` will be `None`.
            await ctx.respond(""You picked a user!"")
        if self.mentionable.role:
            # This is a role. `mentionable.user` will be `None`.
            await ctx.respond(""You picked a role!"")
```

### Autocomplete[#](#autocomplete ""Permanent link"")

Autocomplete is a way for your command to suggest values for an option. The `autocomplete=` kwarg can be used for `int`, `float`, and `str` types.

```
async def autocomplete_response(
    ctx: crescent.AutocompleteContext, option: hikari.AutocompleteInteractionOption
) -> Sequence[tuple[str | int | float, str]]:
    return [(""Some Option"", ""1234"")]

@client.include
@crescent.command
class class_example:
    result = crescent.option(str, ""Respond to the message"", autocomplete=autocomplete_response)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.respond(self.result, ephemeral=True)
```

Options can also be accessed inside the callback. The `ctx.options` dictionary contains snowflakes or values for all the options a user has already filled out. The `ctx.fetch_values` function converts the snowflakes in this dictionary to the correct type and returns it. If you bot object is `hikari.impl.CacheAware` these values are fetched from the cache. Otherwise, they need to be fetched from a REST endpoint.

```
async def fetch_autocomplete_options(
    ctx: crescent.AutocompleteContext, option: hikari.AutocompleteInteractionOption
) -> Sequence[tuple[str, str]]:
    # An option dict where discord objects are all snowflakes.
    options = ctx.options

    # Return options with snowflakes converted into the option types.
    options = await ctx.fetch_options()

    # Return no options.
    return []

bot.run()
```

### Converters[#](#converters ""Permanent link"")

Converters allow you to easily have command options converted into custom values. Converters can be sync or async functions. They must accept a single argument of the type that the option is, and return the converted value or raise an error.

```
def to_number(value: str) -> int:
    return int(value)

@client.include
@crescent.command
class converter_example:
    value = crescent.option(str, ""Actually a number"").convert(to_number)

    async def callback(self, ctx: crescent.Context) -> None:
        reveal_type(self.value)  # int
```

Once all converters have finished running, any exceptions will be combined into a single [`ConverterExceptions`](../../api_reference/exceptions/#crescent.exceptions.ConverterExceptions ""<code class=\""doc-symbol doc-symbol-heading doc-symbol-class\""></code>            <span class=\""doc doc-object-name doc-class-name\"">ConverterExceptions</span>""), which can be caught by using the `catch_command` decorator (see the error handling guide).

## Command Groups[#](#command-groups ""Permanent link"")

Commands can be grouped or grouped into groups of groups. In Crescent these groups are called `groups` and `sub_groups`.

```
import crescent

# Create a group
group = crescent.Group(""outer-group"")
# Create a sub group
sub_group = group.sub_group(""inner-group"")
```

To add a command to a group simply do:

```
@client.include
@group.child
@crescent.command
async def group_command(ctx: crescent.Context):
    ...

@client.include
@sub_group.child
@crescent.command
async def sub_group_command(ctx: crescent.Context):
    ...
```

Do not combine the `group` and `sub_group` decorators. This will cause a command to be registered multiple times.

You can not create a group with the same name as a command.

```
help_group = crescent.Group(""help"")

@client.include
@help_group.child
@crescent.command
async def say(ctx: crescent.Context):
    ...

# This command will cause the bot to crash
@client.include
@crescent.command
async def help(ctx: crescent.Context):
    ...
```"
"# Commands

### Group `dataclass` [#](#crescent.commands.Group ""Permanent link"")

```
Group(
    name: str | LocaleBuilder,
    description: str | LocaleBuilder | None = None,
    hooks: list[CommandHookCallbackT] = list(),
    after_hooks: list[CommandHookCallbackT] = list(),
    default_member_permissions: UndefinedType
    | int
    | Permissions = UNDEFINED,
    context_types: UndefinedType
    | Iterable[ApplicationContextType] = UNDEFINED,
)
```

A command group. A command group is a top level command that contains subcommands and `SubGroup`s.

###### Example[#](#crescent.commands.Group--example ""Permanent link"")

```
import crescent

utils_group = crescent.Group(""utils"")

# This command will appear under the `utils` group in discord.
@client.include
@utils_group.child
@crescent.command
async def ping(ctx: crescent.Context):
    await ctx.respond(""Pong"")
```

#### after\_hooks `class-attribute` `instance-attribute` [#](#crescent.commands.Group.after_hooks ""Permanent link"")

```
after_hooks: list[CommandHookCallbackT] = field(
    default_factory=list
)
```

A list of hooks to run after all commands in this group.

#### context\_types `class-attribute` `instance-attribute` [#](#crescent.commands.Group.context_types ""Permanent link"")

```
context_types: (
    UndefinedType | Iterable[ApplicationContextType]
) = UNDEFINED
```

The contexts in which the command can be used.

#### default\_member\_permissions `class-attribute` `instance-attribute` [#](#crescent.commands.Group.default_member_permissions ""Permanent link"")

```
default_member_permissions: (
    UndefinedType | int | Permissions
) = UNDEFINED
```

The default permissions for all commands in this group.

#### description `class-attribute` `instance-attribute` [#](#crescent.commands.Group.description ""Permanent link"")

```
description: str | LocaleBuilder | None = None
```

The description of the group. The discord API supports this feature but it does not do anything.

#### hooks `class-attribute` `instance-attribute` [#](#crescent.commands.Group.hooks ""Permanent link"")

```
hooks: list[CommandHookCallbackT] = field(
    default_factory=list
)
```

A looks of hooks to run before all commands in this group.

#### name `instance-attribute` [#](#crescent.commands.Group.name ""Permanent link"")

```
name: str | LocaleBuilder
```

The name of the group

#### child [#](#crescent.commands.Group.child ""Permanent link"")

```
child(
    includable: Includable[AppCommandMeta],
) -> Includable[AppCommandMeta]
```

Add a command to this command group.

#### sub\_group [#](#crescent.commands.Group.sub_group ""Permanent link"")

```
sub_group(
    name: str | LocaleBuilder,
    description: str | LocaleBuilder | None = None,
    hooks: list[CommandHookCallbackT] | None = None,
    after_hooks: list[CommandHookCallbackT] | None = None,
) -> SubGroup
```

Create a sub group from this group.

### SubGroup `dataclass` [#](#crescent.commands.SubGroup ""Permanent link"")

```
SubGroup(
    name: str | LocaleBuilder,
    parent: Group,
    description: str | LocaleBuilder | None = None,
    hooks: list[CommandHookCallbackT] = list(),
    after_hooks: list[CommandHookCallbackT] = list(),
)
```

A command subgroup. A command subgroup is a group that is under a top level group.

###### Example[#](#crescent.commands.SubGroup--example ""Permanent link"")

```
import crescent

utils_group = crescent.Group(""utils"")
time_utils_group = utils_group.sub_group(""time"")

# This command will appear under the `utils time` group in discord.
@client.include
@time_utils_group.child
@crescent.command
async def latency(ctx: crescent.Context):
    await ctx.respond(f""The latency is {bot.heartbeat_latency * 1000}ms"")
```

#### after\_hooks `class-attribute` `instance-attribute` [#](#crescent.commands.SubGroup.after_hooks ""Permanent link"")

```
after_hooks: list[CommandHookCallbackT] = field(
    default_factory=list
)
```

A list of hooks to run after all commands in this group.

#### hooks `class-attribute` `instance-attribute` [#](#crescent.commands.SubGroup.hooks ""Permanent link"")

```
hooks: list[CommandHookCallbackT] = field(
    default_factory=list
)
```

A looks of hooks to run before all commands in this group.

#### child [#](#crescent.commands.SubGroup.child ""Permanent link"")

```
child(
    includable: Includable[AppCommandMeta],
) -> Includable[AppCommandMeta]
```

Add a command to this command group.

### command [#](#crescent.commands.command ""Permanent link"")

```
command(
    callback: CommandCallbackT | type[ClassCommandProto],
) -> Includable[AppCommandMeta]
```

```
command(
    *,
    guild: Snowflakeish | None = ...,
    name: str | LocaleBuilder | None = ...,
    description: str | LocaleBuilder | None = ...,
    default_member_permissions: UndefinedType
    | int
    | Permissions = ...,
    context_types: UndefinedOr[
        Iterable[ApplicationContextType]
    ] = ...,
    nsfw: bool | None = ...,
) -> Callable[
    [CommandCallbackT | type[ClassCommandProto]],
    Includable[AppCommandMeta],
]
```

```
command(
    callback: CommandCallbackT
    | type[ClassCommandProto]
    | None = None,
    /,
    *,
    guild: Snowflakeish | None = None,
    name: str | LocaleBuilder | None = None,
    description: str | LocaleBuilder | None = None,
    default_member_permissions: UndefinedType
    | int
    | Permissions = UNDEFINED,
    context_types: UndefinedOr[
        Iterable[ApplicationContextType]
    ] = UNDEFINED,
    nsfw: bool | None = None,
) -> (
    Includable[AppCommandMeta]
    | Callable[
        [CommandCallbackT | type[ClassCommandProto]],
        Includable[AppCommandMeta],
    ]
)
```

Register a slash command.

###### Example[#](#crescent.commands.command--example ""Permanent link"")

```
import hikari
import crescent

bot = hikari.GatewayBot(""YOUR_TOKEN_HERE"")
client = crescent.Client(bot)

@client.include
@crescent.command
async def ping(ctx: crescent.Context):
    await ctx.respond(""Pong"")
```

| PARAMETER | DESCRIPTION |
| --- | --- |
| name | The name of this command. If not specified the function name will be used.TYPE: str | LocaleBuilder | None DEFAULT: None |
| description | The description of this command. If not specified the description will be set to ""No Description"".TYPE: str | LocaleBuilder | None DEFAULT: None |
| guild | The guild to register this command to. If not specified this command will be registered globally.TYPE: Snowflakeish | None DEFAULT: None |
| default_member_permissions | The default permissions for this command. For more information see the discord api docs and the hikari docs.TYPE: UndefinedType | int | Permissions DEFAULT: UNDEFINED |
| context_types | The contexts in which the command can be used. Defaults to all.TYPE: UndefinedOr[Iterable[ApplicationContextType]] DEFAULT: UNDEFINED |
| nsfw | Set to True to mark this command as nsfw. Defaults to None.TYPE: bool | None DEFAULT: None |

### message\_command [#](#crescent.commands.message_command ""Permanent link"")

```
message_command(
    callback: MessageCommandCallbackT,
) -> Includable[AppCommandMeta]
```

```
message_command(
    *,
    guild: Snowflakeish | None = ...,
    name: str | None = ...,
    default_member_permissions: UndefinedType
    | int
    | Permissions = ...,
    context_types: UndefinedOr[
        list[ApplicationContextType]
    ] = ...,
    nsfw: bool | None = ...,
) -> Callable[
    [MessageCommandCallbackT], Includable[AppCommandMeta]
]
```

```
message_command(
    callback: MessageCommandCallbackT | None = None,
    /,
    *,
    guild: Snowflakeish | None = None,
    name: str | None = None,
    default_member_permissions: UndefinedType
    | int
    | Permissions = UNDEFINED,
    context_types: UndefinedOr[
        list[ApplicationContextType]
    ] = UNDEFINED,
    nsfw: bool | None = None,
) -> (
    Callable[
        [MessageCommandCallbackT],
        Includable[AppCommandMeta],
    ]
    | Includable[AppCommandMeta]
)
```

Register a message command. A message command can be used by right clicking on a discord message. Your bot can have up to 5 message commands.

###### Example[#](#crescent.commands.message_command--example ""Permanent link"")

```
import hikari
import crescent

bot = hikari.GatewayBot(""YOUR_TOKEN_HERE"")
client = crescent.Client(bot)

@client.include
@crescent.message_command
async def ping(ctx: crescent.Context, message: hikari.Message):
    await ctx.respond(message.contents)
```

| PARAMETER | DESCRIPTION |
| --- | --- |
| name | The name of this command. If not specified the function name will be used.TYPE: str | None DEFAULT: None |
| guild | The guild to register this command to. If not specified this command will be registered globally.TYPE: Snowflakeish | None DEFAULT: None |
| default_member_permissions | The default permissions for this command. For more information see the discord api docs and the hikari docs.TYPE: UndefinedType | int | Permissions DEFAULT: UNDEFINED |
| context_types | The contexts in which the command can be used. Defaults to all.TYPE: UndefinedOr[list[ApplicationContextType]] DEFAULT: UNDEFINED |
| nsfw | Set to True to mark this command as nsfw. Defaults to None.TYPE: bool | None DEFAULT: None |

### option [#](#crescent.commands.option ""Permanent link"")

```
option(
    option_type: type[PartialChannel]
    | Sequence[type[PartialChannel]],
    description: str | LocaleBuilder = ...,
    *,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[
    InteractionChannel, InteractionChannel
]
```

```
option(
    option_type: type[PartialChannel]
    | Sequence[type[PartialChannel]],
    description: str | LocaleBuilder = ...,
    *,
    default: DEFAULT,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[
    InteractionChannel | DEFAULT,
    InteractionChannel | DEFAULT,
]
```

```
option(
    option_type: USER,
    description: str | LocaleBuilder = ...,
    *,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[User, User]
```

```
option(
    option_type: USER,
    description: str | LocaleBuilder = ...,
    *,
    default: DEFAULT,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[User | DEFAULT, User | DEFAULT]
```

```
option(
    option_type: ROLE,
    description: str | LocaleBuilder = ...,
    *,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[Role, Role]
```

```
option(
    option_type: ROLE,
    description: str | LocaleBuilder = ...,
    *,
    default: DEFAULT,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[Role | DEFAULT, Role | DEFAULT]
```

```
option(
    option_type: ATTACHMENT,
    description: str | LocaleBuilder = ...,
    *,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[Attachment, Attachment]
```

```
option(
    option_type: ATTACHMENT,
    description: str | LocaleBuilder = ...,
    *,
    default: DEFAULT,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[
    Attachment | DEFAULT, Attachment | DEFAULT
]
```

```
option(
    option_type: type[Mentionable],
    description: str | LocaleBuilder = ...,
    *,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[Mentionable, Mentionable]
```

```
option(
    option_type: type[Mentionable],
    description: str | LocaleBuilder = ...,
    *,
    default: DEFAULT,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[
    Mentionable | DEFAULT, Mentionable | DEFAULT
]
```

```
option(
    option_type: type[bool],
    description: str | LocaleBuilder = ...,
    *,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[bool, bool]
```

```
option(
    option_type: type[bool],
    description: str | LocaleBuilder = ...,
    *,
    default: DEFAULT,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[bool | DEFAULT, bool | DEFAULT]
```

```
option(
    option_type: type[int],
    description: str | LocaleBuilder = ...,
    *,
    choices: Sequence[tuple[str | LocaleBuilder, int]]
    | None = ...,
    autocomplete: AutocompleteCallbackT[int] | None = ...,
    min_value: int | None = ...,
    max_value: int | None = ...,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[int, int]
```

```
option(
    option_type: type[int],
    description: str | LocaleBuilder = ...,
    *,
    default: DEFAULT,
    choices: Sequence[tuple[str | LocaleBuilder, int]]
    | None = ...,
    autocomplete: AutocompleteCallbackT[int] | None = ...,
    min_value: int | None = ...,
    max_value: int | None = ...,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[int | DEFAULT, int | DEFAULT]
```

```
option(
    option_type: type[float],
    description: str | LocaleBuilder = ...,
    *,
    choices: Sequence[tuple[str | LocaleBuilder, float]]
    | None = ...,
    autocomplete: AutocompleteCallbackT[float] | None = ...,
    min_value: float | None = ...,
    max_value: float | None = ...,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[float, float]
```

```
option(
    option_type: type[float],
    description: str | LocaleBuilder = ...,
    *,
    default: DEFAULT,
    choices: Sequence[tuple[str | LocaleBuilder, float]]
    | None = ...,
    autocomplete: AutocompleteCallbackT[float] | None = ...,
    min_value: float | None = ...,
    max_value: float | None = ...,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[float | DEFAULT, float | DEFAULT]
```

```
option(
    option_type: type[str],
    description: str | LocaleBuilder = ...,
    *,
    min_length: int | None = ...,
    max_length: int | None = ...,
    choices: Sequence[tuple[str | LocaleBuilder, str]]
    | None = ...,
    autocomplete: AutocompleteCallbackT[str] | None = ...,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[str, str]
```

```
option(
    option_type: type[str],
    description: str | LocaleBuilder = ...,
    *,
    default: DEFAULT,
    min_length: int | None = ...,
    max_length: int | None = ...,
    choices: Sequence[tuple[str | LocaleBuilder, str]]
    | None = ...,
    autocomplete: AutocompleteCallbackT[str] | None = ...,
    name: str | LocaleBuilder | None = ...,
) -> ClassCommandOption[str | DEFAULT, int | DEFAULT]
```

```
option(
    option_type: type[OptionTypesT]
    | Sequence[type[PartialChannel]],
    description: str | LocaleBuilder = ""No Description"",
    *,
    name: str | LocaleBuilder | None = None,
    default: UndefinedOr[Any] = UNDEFINED,
    choices: Sequence[
        tuple[str | LocaleBuilder, str | int | float]
    ]
    | None = None,
    min_value: int | float | None = None,
    max_value: int | float | None = None,
    min_length: int | None = None,
    max_length: int | None = None,
    autocomplete: AutocompleteCallbackT[Any] | None = None,
) -> ClassCommandOption[Any, Any]
```

An option when declaring a command using class syntax.

###### Example[#](#crescent.commands.option--example ""Permanent link"")

```
@client.include
@crescent.command(name=""say"")
class Say:
    word = crescent.option(str)

    async def callback(self, ctx: crescent.Context):
        await ctx.respond(self.word)
```

| PARAMETER | DESCRIPTION |
| --- | --- |
| description | The description for this option. Defaults to ""No Description"".TYPE: str | LocaleBuilder DEFAULT: 'No Description' |
| name | The name to use for this option. By default, the name of the property on the option the option is set to will be used for the name. In the above example the name would be word.TYPE: str | LocaleBuilder | None DEFAULT: None |
| default | The default value for this option. Specifying this will make this option optional.TYPE: UndefinedOr[Any] DEFAULT: UNDEFINED |
| choices | A set of choices a user can pick from for this option. Only available for int, str, and float option types.TYPE: Sequence[tuple[str | LocaleBuilder, str | int | float]] | None DEFAULT: None |
| min_value | The minimum value for a number the user inputs. Only available for int and float option types.TYPE: int | float | None DEFAULT: None |
| man_value | The maximum value for a number the user inputs. Only available for int and float option types. |
| min_length | The minimum length for a str that the user inputs.TYPE: int | None DEFAULT: None |
| max_length | The maximum length for a str that the user inputs.TYPE: int | None DEFAULT: None |
| autocomplete | An autocomplete callback for this option.Example#async def autocomplete_response(
    ctx: crescent.AutocompleteContext, option: hikari.AutocompleteInteractionOption
) -> list[tuple[str, str]]:
    # Return a list of tuples of (option name, option value)
    return [(""Some Option"", ""1234"")]

@client.include
@crescent.command
class autocomplete:
    result = crescent.option(str, ""Respond to the message"", autocomplete=autocomplete_response)

    async def callback(self, ctx: crescent.Context) -> None:
        await ctx.respond(self.result, ephemeral=True)
TYPE: AutocompleteCallbackT[Any] | None DEFAULT: None |

### user\_command [#](#crescent.commands.user_command ""Permanent link"")

```
user_command(
    callback: UserCommandCallbackT,
) -> Includable[AppCommandMeta]
```

```
user_command(
    *,
    guild: Snowflakeish | None = ...,
    name: str | None = ...,
    default_member_permissions: UndefinedType
    | int
    | Permissions = ...,
    context_types: UndefinedOr[
        list[ApplicationContextType]
    ] = ...,
    nsfw: bool | None = ...,
) -> Callable[
    [UserCommandCallbackT], Includable[AppCommandMeta]
]
```

```
user_command(
    callback: UserCommandCallbackT | None = None,
    /,
    *,
    guild: Snowflakeish | None = None,
    name: str | None = None,
    default_member_permissions: UndefinedType
    | int
    | Permissions = UNDEFINED,
    context_types: UndefinedOr[
        list[ApplicationContextType]
    ] = UNDEFINED,
    nsfw: bool | None = None,
) -> (
    Callable[
        [UserCommandCallbackT], Includable[AppCommandMeta]
    ]
    | Includable[AppCommandMeta]
)
```

Register a user command. A user command can be used by right clicking on a discord user. Your bot can have up to 5 user commands.

###### Example[#](#crescent.commands.user_command--example ""Permanent link"")

```
import hikari
import crescent

bot = hikari.GatewayBot(""YOUR_TOKEN_HERE"")
client = crescent.Client(bot)

@client.include
@crescent.user_command
async def ping(ctx: crescent.Context, user: hikari.User):
    await ctx.respond(user.username)
```

| PARAMETER | DESCRIPTION |
| --- | --- |
| name | The name of this command. If not specified the function name will be used.TYPE: str | None DEFAULT: None |
| guild | The guild to register this command to. If not specified this command will be registered globally.TYPE: Snowflakeish | None DEFAULT: None |
| default_member_permissions | The default permissions for this command. For more information see the discord api docs and the hikari docs.TYPE: UndefinedType | int | Permissions DEFAULT: UNDEFINED |
| context_types | The contexts in which the command can be used. Defaults to all.TYPE: UndefinedOr[list[ApplicationContextType]] DEFAULT: UNDEFINED |
| nsfw | Set to True to mark this command as nsfw. Defaults to None.TYPE: bool | None DEFAULT: None |"
"# Locales[#](#locales ""Permanent link"")

Locales are used to localize your bot for different regions and languages.

## Locale Map[#](#locale-map ""Permanent link"")

Locale map is a simple way to use locales is [`LocaleMap`](../../../api_reference/ext/locales/#locales.LocaleMap ""<code class=\""doc-symbol doc-symbol-heading doc-symbol-class\""></code>            <span class=\""doc doc-object-name doc-class-name\"">LocaleMap</span>
<span class=\""doc doc-labels\"">
<small class=\""doc doc-label doc-label-dataclass\""><code>dataclass</code></small>
</span>"").

```
import hikari
import crescent
from crescent.ext import locales

bot = hikari.GatewayBot(token=""YOUR_TOKEN"")
client = crescent.Client(bot)

locale_map = locales.LocaleMap(""name"", en_US=""english-name"", en_GB=""english-name"", fr=""french-name"")

@client.include
@crescent.command(
    name=locale_map,
    description=locales.LocaleMap(
        ""description"",
        en_US=""english-description"",
        en_GB=""english-description"",
        fr=""french-description"",
    ),
)
async def command_2(ctx: crescent.Context) -> None:
    ...
```

The `i18n` library can also be used for locales with the [`i18n`](../../../api_reference/ext/locales/#locales.i18n ""<code class=\""doc-symbol doc-symbol-heading doc-symbol-class\""></code>            <span class=\""doc doc-object-name doc-class-name\"">i18n</span>"") object. You should check the `i18n` documentation for more information.

> [!WARNING]
> Warning
>
> You must install the `i18n` library with `hikari-crescent[i18n]` to use `i18n`.

```
import i18n

i18n.add_translation(""name"", ""english-name"", locale=""en"")
i18n.add_translation(""name"", ""french-name"", locale=""fr"")

i18n.add_translation(""description"", ""english-description"", locale=""en"")
i18n.add_translation(""description"", ""french-description"", locale=""fr"")

# This command will have its name and translation in the french and english locales.
@client.include
@crescent.command(name=locales.i18n(""name""), description=locales.i18n(""description""))
async def command(ctx: crescent.Context) -> None:
    ...
```"
"# Client

### Client [#](#crescent.client.Client ""Permanent link"")

```
Client(
    app: RESTTraits | GatewayTraits,
    model: Any = None,
    *,
    tracked_guilds: Sequence[Snowflakeish] | None = None,
    default_guild: Snowflakeish | None = None,
    update_commands: bool = True,
    allow_unknown_interactions: bool = False,
    command_hooks: list[CommandHookCallbackT] | None = None,
    command_after_hooks: list[CommandHookCallbackT]
    | None = None,
    event_hooks: list[EventHookCallbackT[hk_Event]]
    | None = None,
    event_after_hooks: list[EventHookCallbackT[hk_Event]]
    | None = None,
)
```

The client object is a wrapper around your bot that lets you use Crescent's features.

###### Example[#](#crescent.client.Client--example ""Permanent link"")

```
import hikari
import crescent

bot = hikari.GatewayBot(""your token"")
client = crescent.Client(bot)

# Crescent's features can be used.
@client.include
@crescent.command
async def ping(ctx: crescent.Context):
    await ctx.respong(""Pong"")

bot.run()
```

| PARAMETER | DESCRIPTION |
| --- | --- |
| app | The hikari bot instance.TYPE: RESTTraits | GatewayTraits |
| model | An object to store global data. This object can be accessed with the Plugin.model property.Example## In bot.py
bot = hikari.GatewayBot(""your token"")
client = crescent.Client(bot, ""I am a model"")

client.plugins.load(""plugin"")

# In plugin.py
plugin = crescent.Plugin()

@plugin.on_load
def on_load():
    # Print the model object that was set earlier to the console.
    print(plugin.model)  # prints ""I am a model""
If no model is set, the model will default to None.TYPE: Any DEFAULT: None |
| tracked_guilds | The guilds to compare posted commands to. Commands will not be automatically removed from guilds that aren't in this list. This should be kept to as little guilds as possible to prevent rate limits.TYPE: Sequence[Snowflakeish] | None DEFAULT: None |
| default_guild | The guild to post application commands to by default. If this is None, slash commands will be posted globally.TYPE: Snowflakeish | None DEFAULT: None |
| update_commands | If True or not specified, update commands when the bot starts. Only works for gateway-based bots.TYPE: bool DEFAULT: True |
| command_hooks | List of hooks to run before all commands.TYPE: list[CommandHookCallbackT] | None DEFAULT: None |
| command_after_hooks | List of hooks to run after all commands.TYPE: list[CommandHookCallbackT] | None DEFAULT: None |

#### commands `property` [#](#crescent.client.Client.commands ""Permanent link"")

```
commands: CommandHandler
```

Return the command handler object. This object lets you access command information that is not normally accessible. See `CommandHandler` for more information.

#### plugins `property` [#](#crescent.client.Client.plugins ""Permanent link"")

```
plugins: PluginManager
```

Return the plugin manager object. This object lets you load and unload plugins. See `PluginManager` for more information.

#### include [#](#crescent.client.Client.include ""Permanent link"")

```
include(obj: INCLUDABLE) -> INCLUDABLE
```

```
include(
    obj: None = ...,
) -> Callable[[INCLUDABLE], INCLUDABLE]
```

```
include(
    obj: INCLUDABLE | None = None,
) -> INCLUDABLE | Callable[[INCLUDABLE], INCLUDABLE]
```

Register an includable object, such as an event or command handler.

###### Example[#](#crescent.client.Client.include--example ""Permanent link"")

```
client = crescent.Client(...)

@client.include
@crescent.command
async def ping(ctx: crescent.Context):
    await ctx.respong(""Pong"")
```

#### on\_crescent\_autocomplete\_error `async` [#](#crescent.client.Client.on_crescent_autocomplete_error ""Permanent link"")

```
on_crescent_autocomplete_error(
    exc: Exception,
    ctx: AutocompleteContext,
    option: AutocompleteInteractionOption,
    was_handled: bool,
) -> None
```

This function is run when there is an error in an autocomplete handler that is not caught with any error handlers. You can inherit from this class and override this function to change default error handling.

#### on\_crescent\_command\_error `async` [#](#crescent.client.Client.on_crescent_command_error ""Permanent link"")

```
on_crescent_command_error(
    exc: Exception, ctx: Context, was_handled: bool
) -> None
```

This function is run when there is an error in a crescent command that is not caught with any error handlers. You can inherit from this class and override this function to change default error handling.

#### on\_crescent\_event\_error `async` [#](#crescent.client.Client.on_crescent_event_error ""Permanent link"")

```
on_crescent_event_error(
    exc: Exception, event: hk_Event, was_handled: bool
) -> None
```

This function is run when there is an error in a crescent event that is not caught with any error handlers. You can inherit from this class and override this function to change default error handling.

### GatewayTraits [#](#crescent.client.GatewayTraits ""Permanent link"")

Bases: `[EventManagerAware](https://docs.hikari-py.dev/en/latest/reference/hikari/traits/#hikari.traits.EventManagerAware ""<code>hikari.traits.EventManagerAware</code>"")`, `[RESTAware](https://docs.hikari-py.dev/en/latest/reference/hikari/traits/#hikari.traits.RESTAware ""<code>hikari.traits.RESTAware</code>"")`, `[Protocol](https://docs.python.org/3.9/library/typing.html#typing.Protocol ""<code>typing.Protocol</code>"")`

The traits crescent requires for a gateway-based bot.

### RESTTraits [#](#crescent.client.RESTTraits ""Permanent link"")

Bases: `[InteractionServerAware](https://docs.hikari-py.dev/en/latest/reference/hikari/traits/#hikari.traits.InteractionServerAware ""<code>hikari.InteractionServerAware</code>"")`, `[RESTAware](https://docs.hikari-py.dev/en/latest/reference/hikari/traits/#hikari.traits.RESTAware ""<code>hikari.traits.RESTAware</code>"")`, `[Protocol](https://docs.python.org/3.9/library/typing.html#typing.Protocol ""<code>typing.Protocol</code>"")`

The base traits crescents requires for a REST-based bot."
"# Errors

### catch\_autocomplete [#](#crescent.errors.catch_autocomplete ""Permanent link"")

```
catch_autocomplete(
    *exceptions: type[Exception],
) -> Callable[
    [AutocompleteErrorHandlerCallbackT[Any]],
    Includable[AutocompleteErrorHandlerCallbackT[Any]],
]
```

Catch an exception or subclasses of an exception passed into this function when the exception is raised in an autocomplete handler.

###### Example[#](#crescent.errors.catch_autocomplete--example ""Permanent link"")

```
@client.include
@crescent.catch_autocomplete(Exception)
async def on_autocomplete_random_error(
    exc: Exception,
    ctx: crescent.AutocompleteContext,
    inter: hikari.AutocompleteInteractionOption,
) -> None:
    print(f""{exc} raised in autocomplete for {ctx.command}!"")

# An autocomplete callback that a command is using.
async def example_autocomplete(
    ctx: crescent.AutocompleteContext, option: hikari.AutocompleteInteractionOption
) -> list[tuple[str, str]]:
    raise Exception
```

### catch\_command [#](#crescent.errors.catch_command ""Permanent link"")

```
catch_command(
    *exceptions: type[Exception],
) -> Callable[
    [CommandErrorHandlerCallbackT[Any]],
    Includable[CommandErrorHandlerCallbackT[Any]],
]
```

Catch an exception or subclasses of an exception passed into this function when the exception is raised in a command.

###### Example[#](#crescent.errors.catch_command--example ""Permanent link"")

```
@client.include
@crescent.catch_command(Exception)
async def handler(exc: Exception, ctx: crescent.Context) -> None:
    await ctx.respond(f""{exc} raised in {ctx.command}!"")

@client.include
@crescent.command
async def example_command(ctx: crescent.Context):
    ...
```

### catch\_event [#](#crescent.errors.catch_event ""Permanent link"")

```
catch_event(
    *exceptions: type[Exception],
) -> Callable[
    [EventErrorHandlerCallbackT[Any]],
    Includable[EventErrorHandlerCallbackT[Any]],
]
```

Catch an exception or subclasses of an exception passed into this function when the exception is raised in an event.

###### Example[#](#crescent.errors.catch_event--example ""Permanent link"")

```
@client.include
@crescent.catch_event(Exception)
async def handler(exc: Exception, event: hikari.Event) -> None:
    print(f""{exc} raised in {event}!"")

@client.include
@crescent.event
async def example_error(event: hikari.MessageCreateEvent) -> None:
    raise Exception
```"
"# Typedefs

### ClassCommandProto [#](#crescent.typedefs.ClassCommandProto ""Permanent link"")

Bases: `[Protocol](https://docs.python.org/3.9/library/typing.html#typing.Protocol ""<code>typing.Protocol</code>"")`

A type with all the attributes required for class commands."
"# Events

### event [#](#crescent.events.event ""Permanent link"")

```
event(
    callback: CallbackT[EventT],
) -> Includable[EventMeta[EventT]]
```

```
event(
    *, event_type: type[EventT] | None
) -> Callable[
    [CallbackT[EventT]], Includable[EventMeta[EventT]]
]
```

```
event(
    callback: CallbackT[EventT] | None = None,
    /,
    *,
    event_type: type[EventT] | None = None,
) -> (
    Callable[
        [CallbackT[EventT]], Includable[EventMeta[EventT]]
    ]
    | Includable[EventMeta[EventT]]
)
```

Listen to an event. This function should be used instead of `hikari.GatewayBot.listen` whenever possible.

###### Example[#](#crescent.events.event--example ""Permanent link"")

```
import crescent

client = crescent.Client(...)

# Listen to the message create event
@client.include
@crescent.event
async def ping(event: hikari.MessageCreateEvent):
    ...
```

Event types can be provided using the `event_type` kwarg if you do not want to use type annotations."
"# Mentionable

### Mentionable `dataclass` [#](#crescent.mentionable.Mentionable ""Permanent link"")

```
Mentionable(user: User | None, role: Role | None)
```

Represent's discord's mentionable type. A mentionable can be a User or Role. Not that it can not be both.

###### Example[#](#crescent.mentionable.Mentionable--example ""Permanent link"")

```
@client.include
@crescent.command
async def command(ctx: crescent.Context, mentionable: crescent.Mentionable):
    if mentionable.is_user:
        user = mentionable.unwrap_user()
    else:
        role = mentionable.unwrap_role()
```"
"# Plugin

### Plugin [#](#crescent.plugin.Plugin ""Permanent link"")

```
Plugin(
    *,
    command_hooks: list[CommandHookCallbackT] | None = None,
    command_after_hooks: list[CommandHookCallbackT]
    | None = None,
    event_hooks: list[EventHookCallbackT[Event]]
    | None = None,
    event_after_hooks: list[EventHookCallbackT[Event]]
    | None = None,
)
```

Bases: `[Generic](https://docs.python.org/3.9/library/typing.html#typing.Generic ""<code>typing.Generic</code>"")[BotT, ModelT]`

A plugin object to be used in a plugin file.

###### Example[#](#crescent.plugin.Plugin--example ""Permanent link"")

```
import hikari
import crescent

plugin = crescent.Plugin[hikari.GatewayBot, None]()
```

You can load this file with `PluginManager.load`

### PluginManager [#](#crescent.plugin.PluginManager ""Permanent link"")

```
PluginManager(client: Client)
```

A class that allows you to load and unload plugins. You should not construct this class yourself. It will be provided to you as the `clients.plugins` property when you construct a `Client` object.

#### load [#](#crescent.plugin.PluginManager.load ""Permanent link"")

```
load(
    path: str, /, *, refresh: bool = ...
) -> Plugin[Any, Any]
```

```
load(
    path: str, *, strict: Literal[True], refresh: bool = ...
) -> Plugin[Any, Any]
```

```
load(
    path: str,
    *,
    strict: Literal[False],
    refresh: bool = ...,
) -> Plugin[Any, Any] | None
```

```
load(
    path: str, refresh: bool = ..., strict: bool = ...
) -> Plugin[Any, Any] | None
```

```
load(
    path: str, refresh: bool = False, strict: bool = True
) -> Plugin[Any, Any] | None
```

Load a plugin from the module path.

```
import crescent

bot = crescent.Bot(token=...)

bot.plugins.load(""folder.plugin"")
```

| PARAMETER | DESCRIPTION |
| --- | --- |
| path | The module path for the plugin.TYPE: str |
| refresh | Whether or not to reload the plugin and the plugin's module.TYPE: bool DEFAULT: False |
| strict | If false, the function will not error when module file does not have a plugin variable.TYPE: bool DEFAULT: True |

#### load\_folder [#](#crescent.plugin.PluginManager.load_folder ""Permanent link"")

```
load_folder(
    path: str, refresh: bool = False, strict: bool = True
) -> list[Plugin[Any, Any]]
```

Loads plugins from a folder.

```
import crescent
import hikari

bot = hikari.GatewayBot(token=...)
client = crescent.Client(bot)

client.plugins.load(""project.plugin_folder"")
```

If a file is attempted to be loaded that does not have a plugin variable, a `ValueError` will be raised. Files who's names start with an underscore will not be loaded.

| PARAMETER | DESCRIPTION |
| --- | --- |
| path | The path to the folder that contains the plugins.TYPE: str |
| refresh | Whether or not to reload the plugin and the plugin's module.TYPE: bool DEFAULT: False |
| strict | If false, the function will not error when a file does not have a plugin variable.TYPE: bool DEFAULT: True |

Returns: A list of plugins that were loaded.

#### unload [#](#crescent.plugin.PluginManager.unload ""Permanent link"")

```
unload(path: str) -> None
```

Unload a plugin.

| PARAMETER | DESCRIPTION |
| --- | --- |
| path | The module path for the plugin.TYPE: str |

#### unload\_all [#](#crescent.plugin.PluginManager.unload_all ""Permanent link"")

```
unload_all() -> None
```

Unload all of the plugins that are currently loaded."
"# Locale

### LocaleBuilder [#](#crescent.locale.LocaleBuilder ""Permanent link"")

Bases: `[ABC](https://docs.python.org/3.9/library/abc.html#abc.ABC ""<code>abc.ABC</code>"")`

A class that can be inherited from to created APIs to use locales in your code.

#### fallback `abstractmethod` `property` [#](#crescent.locale.LocaleBuilder.fallback ""Permanent link"")

```
fallback: str
```

Return the name used when there is no localization for a language.

#### build `abstractmethod` [#](#crescent.locale.LocaleBuilder.build ""Permanent link"")

```
build() -> Mapping[str, str]
```

Builds the locales for a command. Returns a `Mapping` of language codes to strings.

[Discord API Docs Localization.](https://discord.com/developers/docs/interactions/application-commands#localization)"
"# Context

### AutocompleteContext `dataclass` [#](#crescent.context.AutocompleteContext ""Permanent link"")

```
AutocompleteContext(
    interaction: PartialInteraction,
    app: GatewayTraits | RESTTraits,
    client: Client,
    application_id: Snowflake,
    type: int,
    token: str,
    id: Snowflake,
    version: int,
    channel_id: Snowflake,
    guild_id: Snowflake | None,
    registered_guild_id: Snowflake | None,
    user: User,
    member: Member | None,
    entitlements: Sequence[hikari.Entitlement],
    locale: Locale,
    command: str,
    command_type: hikari.CommandType,
    group: str | None,
    sub_group: str | None,
    options: dict[str, Any],
    _has_created_response: bool,
    _has_deferred_response: bool,
    _rest_interaction_future: Future[
        InteractionResponseBuilder
    ]
    | None,
)
```

Bases: `[InteractionContext](#crescent.context.InteractionContext ""<code class=\""doc-symbol doc-symbol-heading doc-symbol-class\""></code>            <span class=\""doc doc-object-name doc-class-name\"">InteractionContext</span>
<span class=\""doc doc-labels\"">
<small class=\""doc doc-label doc-label-dataclass\""><code>dataclass</code></small>
</span> (<code>crescent.context.interaction_context.InteractionContext</code>)"")`

Represents the context for autocomplete interactions

#### app `instance-attribute` [#](#crescent.context.AutocompleteContext.app ""Permanent link"")

```
app: GatewayTraits | RESTTraits
```

The application instance.

#### application\_id `instance-attribute` [#](#crescent.context.AutocompleteContext.application_id ""Permanent link"")

```
application_id: Snowflake
```

The ID for the client that this interaction belongs to.

#### channel\_id `instance-attribute` [#](#crescent.context.AutocompleteContext.channel_id ""Permanent link"")

```
channel_id: Snowflake
```

The channel ID of the channel that the interaction was used in.

#### client `instance-attribute` [#](#crescent.context.AutocompleteContext.client ""Permanent link"")

```
client: Client
```

The crescent Client instance.

#### command `instance-attribute` [#](#crescent.context.AutocompleteContext.command ""Permanent link"")

```
command: str
```

The name of the command.

#### entitlements `instance-attribute` [#](#crescent.context.AutocompleteContext.entitlements ""Permanent link"")

```
entitlements: Sequence[hikari.Entitlement]
```

For monetized apps, any entitlements involving this user. Represents access to SKUs.

#### guild\_id `instance-attribute` [#](#crescent.context.AutocompleteContext.guild_id ""Permanent link"")

```
guild_id: Snowflake | None
```

The guild ID of the guild that this interaction was used in.

#### id `instance-attribute` [#](#crescent.context.AutocompleteContext.id ""Permanent link"")

```
id: Snowflake
```

The ID of the interaction.

#### interaction `instance-attribute` [#](#crescent.context.AutocompleteContext.interaction ""Permanent link"")

```
interaction: AutocompleteInteraction
```

The interaction object.

#### member `instance-attribute` [#](#crescent.context.AutocompleteContext.member ""Permanent link"")

```
member: Member | None
```

The member object for the user that triggered this interaction, if used in a guild.

#### options `instance-attribute` [#](#crescent.context.AutocompleteContext.options ""Permanent link"")

```
options: dict[str, Any]
```

The options that were provided by the user.

#### registered\_guild\_id `instance-attribute` [#](#crescent.context.AutocompleteContext.registered_guild_id ""Permanent link"")

```
registered_guild_id: Snowflake | None
```

The guild ID of the guild that this command is registered to.

#### token `instance-attribute` [#](#crescent.context.AutocompleteContext.token ""Permanent link"")

```
token: str
```

The token for the interaction.

#### type `instance-attribute` [#](#crescent.context.AutocompleteContext.type ""Permanent link"")

```
type: int
```

The type of the interaction.

#### user `instance-attribute` [#](#crescent.context.AutocompleteContext.user ""Permanent link"")

```
user: User
```

The user who triggered this command interaction.

#### version `instance-attribute` [#](#crescent.context.AutocompleteContext.version ""Permanent link"")

```
version: int
```

Version of the interaction system this interaction is under.

#### into [#](#crescent.context.AutocompleteContext.into ""Permanent link"")

```
into(context_t: Type[ContextT]) -> ContextT
```

Convert to a context of a different type.

### Context `dataclass` [#](#crescent.context.Context ""Permanent link"")

```
Context(
    interaction: PartialInteraction,
    app: GatewayTraits | RESTTraits,
    client: Client,
    application_id: Snowflake,
    type: int,
    token: str,
    id: Snowflake,
    version: int,
    channel_id: Snowflake,
    guild_id: Snowflake | None,
    registered_guild_id: Snowflake | None,
    user: User,
    member: Member | None,
    entitlements: Sequence[hikari.Entitlement],
    locale: Locale,
    command: str,
    command_type: hikari.CommandType,
    group: str | None,
    sub_group: str | None,
    options: dict[str, Any],
    _has_created_response: bool,
    _has_deferred_response: bool,
    _rest_interaction_future: Future[
        InteractionResponseBuilder
    ]
    | None,
)
```

Bases: `[InteractionContext](#crescent.context.InteractionContext ""<code class=\""doc-symbol doc-symbol-heading doc-symbol-class\""></code>            <span class=\""doc doc-object-name doc-class-name\"">InteractionContext</span>
<span class=\""doc doc-labels\"">
<small class=\""doc doc-label doc-label-dataclass\""><code>dataclass</code></small>
</span> (<code>crescent.context.interaction_context.InteractionContext</code>)"")`

Represents the context for command interactions

#### app `instance-attribute` [#](#crescent.context.Context.app ""Permanent link"")

```
app: GatewayTraits | RESTTraits
```

The application instance.

#### application\_id `instance-attribute` [#](#crescent.context.Context.application_id ""Permanent link"")

```
application_id: Snowflake
```

The ID for the client that this interaction belongs to.

#### channel `property` [#](#crescent.context.Context.channel ""Permanent link"")

```
channel: PermissibleGuildChannel | GuildThreadChannel | None
```

Get this context's guild channel or thread from the cache.

> 📝 This will always be `None` for interactions triggered in a DM channel.

#### channel\_id `instance-attribute` [#](#crescent.context.Context.channel_id ""Permanent link"")

```
channel_id: Snowflake
```

The channel ID of the channel that the interaction was used in.

#### client `instance-attribute` [#](#crescent.context.Context.client ""Permanent link"")

```
client: Client
```

The crescent Client instance.

#### command `instance-attribute` [#](#crescent.context.Context.command ""Permanent link"")

```
command: str
```

The name of the command.

#### entitlements `instance-attribute` [#](#crescent.context.Context.entitlements ""Permanent link"")

```
entitlements: Sequence[hikari.Entitlement]
```

For monetized apps, any entitlements involving this user. Represents access to SKUs.

#### guild `property` [#](#crescent.context.Context.guild ""Permanent link"")

```
guild: GatewayGuild | None
```

Get this context's guild from the cache.

#### guild\_id `instance-attribute` [#](#crescent.context.Context.guild_id ""Permanent link"")

```
guild_id: Snowflake | None
```

The guild ID of the guild that this interaction was used in.

#### id `instance-attribute` [#](#crescent.context.Context.id ""Permanent link"")

```
id: Snowflake
```

The ID of the interaction.

#### interaction `instance-attribute` [#](#crescent.context.Context.interaction ""Permanent link"")

```
interaction: CommandInteraction
```

The interaction object.

#### member `instance-attribute` [#](#crescent.context.Context.member ""Permanent link"")

```
member: Member | None
```

The member object for the user that triggered this interaction, if used in a guild.

#### options `instance-attribute` [#](#crescent.context.Context.options ""Permanent link"")

```
options: dict[str, Any]
```

The options that were provided by the user.

#### registered\_guild\_id `instance-attribute` [#](#crescent.context.Context.registered_guild_id ""Permanent link"")

```
registered_guild_id: Snowflake | None
```

The guild ID of the guild that this command is registered to.

#### token `instance-attribute` [#](#crescent.context.Context.token ""Permanent link"")

```
token: str
```

The token for the interaction.

#### type `instance-attribute` [#](#crescent.context.Context.type ""Permanent link"")

```
type: int
```

The type of the interaction.

#### user `instance-attribute` [#](#crescent.context.Context.user ""Permanent link"")

```
user: User
```

The user who triggered this command interaction.

#### version `instance-attribute` [#](#crescent.context.Context.version ""Permanent link"")

```
version: int
```

Version of the interaction system this interaction is under.

#### defer `async` [#](#crescent.context.Context.defer ""Permanent link"")

```
defer(ephemeral: bool = False) -> None
```

Defer this interaction response, allowing you to respond within the next 15 minutes.

#### delete `async` [#](#crescent.context.Context.delete ""Permanent link"")

```
delete() -> None
```

Delete the previous response to this interaction.

###### Example[#](#crescent.context.Context.delete--example ""Permanent link"")

```
import asyncio

@client.include
@crescent.command
async def command(ctx: crescent.Context):
    await ctx.respond(""im going to disappear"")
    await asyncio.sleep(3)
    await ctx.delete()
```

#### edit `async` [#](#crescent.context.Context.edit ""Permanent link"")

```
edit(
    content: UndefinedNoneOr[Any] = UNDEFINED,
    *,
    attachment: UndefinedNoneOr[
        Resourceish | Attachment
    ] = UNDEFINED,
    attachments: UndefinedNoneOr[
        Sequence[Resourceish | Attachment]
    ] = UNDEFINED,
    component: UndefinedNoneOr[
        ComponentBuilder
    ] = UNDEFINED,
    components: UndefinedNoneOr[
        Sequence[ComponentBuilder]
    ] = UNDEFINED,
    embed: UndefinedNoneOr[Embed] = UNDEFINED,
    embeds: UndefinedNoneOr[Sequence[Embed]] = UNDEFINED,
    mentions_everyone: UndefinedOr[bool] = UNDEFINED,
    user_mentions: UndefinedOr[
        SnowflakeishSequence[PartialUser] | bool
    ] = UNDEFINED,
    role_mentions: UndefinedOr[
        SnowflakeishSequence[PartialRole] | bool
    ] = UNDEFINED,
) -> Message
```

Edit the previous response to this interaction.

###### Example[#](#crescent.context.Context.edit--example ""Permanent link"")

```
import asyncio

@client.include
@crescent.command
async def command(ctx: crescent.Context):
    await ctx.respond(""hello there"")
    await asyncio.sleep(3)
    await ctx.edit(""general kenobi"")
```

> 📝 Message flags are ignored in followup responses.

| PARAMETER | DESCRIPTION |
| --- | --- |
| content | The content to send.TYPE: UndefinedNoneOr[Any] DEFAULT: UNDEFINED |
| attachment | A single attachment to send.TYPE: UndefinedNoneOr[Resourceish | Attachment] DEFAULT: UNDEFINED |
| attachments | A list of attachments to send.TYPE: UndefinedNoneOr[Sequence[Resourceish | Attachment]] DEFAULT: UNDEFINED |
| component | A single component to send.TYPE: UndefinedNoneOr[ComponentBuilder] DEFAULT: UNDEFINED |
| components | A list of components to send.TYPE: UndefinedNoneOr[Sequence[ComponentBuilder]] DEFAULT: UNDEFINED |
| embed | A single embed to send.TYPE: UndefinedNoneOr[Embed] DEFAULT: UNDEFINED |
| embeds | A list of embeds to send.TYPE: UndefinedNoneOr[Sequence[Embed]] DEFAULT: UNDEFINED |
| mentions_everyone | Allow @everyone and @here to ping users if set to True.TYPE: UndefinedOr[bool] DEFAULT: UNDEFINED |
| user_mentions | If True, all mentioned users will be sent a notification. If a list of users is provided, only those users will be mentioned.TYPE: UndefinedOr[SnowflakeishSequence[PartialUser] | bool] DEFAULT: UNDEFINED |
| role_mentions | If True, all mentioned roles will be sent a notification. If a list of roles is provided, only those roles will be mentioned.TYPE: UndefinedOr[SnowflakeishSequence[PartialRole] | bool] DEFAULT: UNDEFINED |

#### into [#](#crescent.context.Context.into ""Permanent link"")

```
into(context_t: Type[ContextT]) -> ContextT
```

Convert to a context of a different type.

#### respond `async` [#](#crescent.context.Context.respond ""Permanent link"")

```
respond(
    content: UndefinedOr[Any] = UNDEFINED,
    *,
    ensure_message: Literal[True],
    ephemeral: bool = False,
    flags: int | MessageFlag | UndefinedType = UNDEFINED,
    tts: UndefinedOr[bool] = UNDEFINED,
    attachment: UndefinedOr[Resourceish] = UNDEFINED,
    attachments: UndefinedOr[
        Sequence[Resourceish]
    ] = UNDEFINED,
    component: UndefinedOr[ComponentBuilder] = UNDEFINED,
    components: UndefinedOr[
        Sequence[ComponentBuilder]
    ] = UNDEFINED,
    embed: UndefinedOr[Embed] = UNDEFINED,
    embeds: UndefinedOr[Sequence[Embed]] = UNDEFINED,
    mentions_everyone: UndefinedOr[bool] = UNDEFINED,
    user_mentions: UndefinedOr[
        SnowflakeishSequence[PartialUser] | bool
    ] = UNDEFINED,
    role_mentions: UndefinedOr[
        SnowflakeishSequence[PartialRole] | bool
    ] = UNDEFINED,
) -> Message
```

```
respond(
    content: UndefinedOr[Any] = UNDEFINED,
    *,
    ephemeral: bool = False,
    flags: int | MessageFlag | UndefinedType = UNDEFINED,
    tts: UndefinedOr[bool] = UNDEFINED,
    attachment: UndefinedOr[Resourceish] = UNDEFINED,
    attachments: UndefinedOr[
        Sequence[Resourceish]
    ] = UNDEFINED,
    component: UndefinedOr[ComponentBuilder] = UNDEFINED,
    components: UndefinedOr[
        Sequence[ComponentBuilder]
    ] = UNDEFINED,
    embed: UndefinedOr[Embed] = UNDEFINED,
    embeds: UndefinedOr[Sequence[Embed]] = UNDEFINED,
    mentions_everyone: UndefinedOr[bool] = UNDEFINED,
    user_mentions: UndefinedOr[
        SnowflakeishSequence[PartialUser] | bool
    ] = UNDEFINED,
    role_mentions: UndefinedOr[
        SnowflakeishSequence[PartialRole] | bool
    ] = UNDEFINED,
    ensure_message: Literal[False] = ...,
) -> Message | None
```

```
respond(
    content: UndefinedOr[Any] = UNDEFINED,
    *,
    ephemeral: bool = False,
    flags: int | MessageFlag | UndefinedType = UNDEFINED,
    tts: UndefinedOr[bool] = UNDEFINED,
    attachment: UndefinedOr[Resourceish] = UNDEFINED,
    attachments: UndefinedOr[
        Sequence[Resourceish]
    ] = UNDEFINED,
    component: UndefinedOr[ComponentBuilder] = UNDEFINED,
    components: UndefinedOr[
        Sequence[ComponentBuilder]
    ] = UNDEFINED,
    embed: UndefinedOr[Embed] = UNDEFINED,
    embeds: UndefinedOr[Sequence[Embed]] = UNDEFINED,
    mentions_everyone: UndefinedOr[bool] = UNDEFINED,
    user_mentions: UndefinedOr[
        SnowflakeishSequence[PartialUser] | bool
    ] = UNDEFINED,
    role_mentions: UndefinedOr[
        SnowflakeishSequence[PartialRole] | bool
    ] = UNDEFINED,
    ensure_message: bool = False,
) -> Message | None
```

Respond to an interaction. This function can be used multiple times for one interaction,

###### Example[#](#crescent.context.Context.respond--example ""Permanent link"")

```
@client.include
@crescent.command
async def command(ctx: crescent.Context):
    # Initial response
    await ctx.respond(""hello"")
    # After the first response, a followup response will be sent.
    await ctx.respond(""word"")
```

> 📝 Message flags are ignored in followup responses.

| PARAMETER | DESCRIPTION |
| --- | --- |
| content | The content to send.TYPE: UndefinedOr[Any] DEFAULT: UNDEFINED |
| ephemeral | Send this message as ephemeral if set to true. Ephemeral messages can be dismissed by the user, similar to Clyde messages. This kwarg only affects the initial response to an interaction.TYPE: bool DEFAULT: False |
| flags | Message flags to send with the message. You do not need to use this, and exists for compatibility in the future. Instead set the ephemeral kwarg to True.TYPE: int | MessageFlag | UndefinedType DEFAULT: UNDEFINED |
| tts | If true, send a text to speech message.TYPE: UndefinedOr[bool] DEFAULT: UNDEFINED |
| attachment | A single attachment to send.TYPE: UndefinedOr[Resourceish] DEFAULT: UNDEFINED |
| attachments | A list of attachments to send.TYPE: UndefinedOr[Sequence[Resourceish]] DEFAULT: UNDEFINED |
| component | A single component to send.TYPE: UndefinedOr[ComponentBuilder] DEFAULT: UNDEFINED |
| components | A list of components to send.TYPE: UndefinedOr[Sequence[ComponentBuilder]] DEFAULT: UNDEFINED |
| embed | A single embed to send.TYPE: UndefinedOr[Embed] DEFAULT: UNDEFINED |
| embeds | A list of embeds to send.TYPE: UndefinedOr[Sequence[Embed]] DEFAULT: UNDEFINED |
| mentions_everyone | Allow @everyone and @here to ping users if set to True.TYPE: UndefinedOr[bool] DEFAULT: UNDEFINED |
| user_mentions | If True, all mentioned users will be sent a notification. If a list of users is provided, only those users will be mentioned.TYPE: UndefinedOr[SnowflakeishSequence[PartialUser] | bool] DEFAULT: UNDEFINED |
| role_mentions | If True, all mentioned roles will be sent a notification. If a list of roles is provided, only those roles will be mentioned.TYPE: UndefinedOr[SnowflakeishSequence[PartialRole] | bool] DEFAULT: UNDEFINED |
| ensure_message | A message is not returned the first time you use Context.respond. Set ensure_message=True to automatically fetch a message and return it.TYPE: bool DEFAULT: False |

#### respond\_with\_builder `async` [#](#crescent.context.Context.respond_with_builder ""Permanent link"")

```
respond_with_builder(
    builder: ResponseBuilderT, ensure_message: bool = False
) -> Message | None
```

Respond to an interaction with a builder.

| PARAMETER | DESCRIPTION |
| --- | --- |
| builder | The builder to respond with.TYPE: ResponseBuilderT |
| ensure_message | If an InteractionMessageBuilder is passed, this will fetch the message and return it. Otherwise does nothing.TYPE: bool DEFAULT: False |

| RAISES | DESCRIPTION |
| --- | --- |
| InteractionAlreadyAcknowledgedError | Raised when calling this method after responding to an interaction. |

| RETURNS | DESCRIPTION |
| --- | --- |
| Message | None | The message if ensure_message is True and a message builder was passed. |

#### respond\_with\_modal `async` [#](#crescent.context.Context.respond_with_modal ""Permanent link"")

```
respond_with_modal(
    title: str,
    custom_id: str,
    components: Sequence[ComponentBuilder],
) -> None
```

Respond to an interaction with a modal.

| PARAMETER | DESCRIPTION |
| --- | --- |
| title | The title of the modal.TYPE: str |
| custom_id | The custom id of the modal.TYPE: str |
| components | The components to add to the modal.TYPE: Sequence[ComponentBuilder] |

| RAISES | DESCRIPTION |
| --- | --- |
| InteractionAlreadyAcknowledgedError | Raised when calling this method after responding to an interaction. |

### InteractionContext `dataclass` [#](#crescent.context.InteractionContext ""Permanent link"")

```
InteractionContext(
    interaction: PartialInteraction,
    app: GatewayTraits | RESTTraits,
    client: Client,
    application_id: Snowflake,
    type: int,
    token: str,
    id: Snowflake,
    version: int,
    channel_id: Snowflake,
    guild_id: Snowflake | None,
    registered_guild_id: Snowflake | None,
    user: User,
    member: Member | None,
    entitlements: Sequence[hikari.Entitlement],
    locale: Locale,
    command: str,
    command_type: hikari.CommandType,
    group: str | None,
    sub_group: str | None,
    options: dict[str, Any],
    _has_created_response: bool,
    _has_deferred_response: bool,
    _rest_interaction_future: Future[
        InteractionResponseBuilder
    ]
    | None,
)
```

Represents the context for interactions

#### app `instance-attribute` [#](#crescent.context.InteractionContext.app ""Permanent link"")

```
app: GatewayTraits | RESTTraits
```

The application instance.

#### application\_id `instance-attribute` [#](#crescent.context.InteractionContext.application_id ""Permanent link"")

```
application_id: Snowflake
```

The ID for the client that this interaction belongs to.

#### channel\_id `instance-attribute` [#](#crescent.context.InteractionContext.channel_id ""Permanent link"")

```
channel_id: Snowflake
```

The channel ID of the channel that the interaction was used in.

#### client `instance-attribute` [#](#crescent.context.InteractionContext.client ""Permanent link"")

```
client: Client
```

The crescent Client instance.

#### command `instance-attribute` [#](#crescent.context.InteractionContext.command ""Permanent link"")

```
command: str
```

The name of the command.

#### entitlements `instance-attribute` [#](#crescent.context.InteractionContext.entitlements ""Permanent link"")

```
entitlements: Sequence[hikari.Entitlement]
```

For monetized apps, any entitlements involving this user. Represents access to SKUs.

#### guild\_id `instance-attribute` [#](#crescent.context.InteractionContext.guild_id ""Permanent link"")

```
guild_id: Snowflake | None
```

The guild ID of the guild that this interaction was used in.

#### id `instance-attribute` [#](#crescent.context.InteractionContext.id ""Permanent link"")

```
id: Snowflake
```

The ID of the interaction.

#### interaction `instance-attribute` [#](#crescent.context.InteractionContext.interaction ""Permanent link"")

```
interaction: PartialInteraction
```

The interaction object.

#### member `instance-attribute` [#](#crescent.context.InteractionContext.member ""Permanent link"")

```
member: Member | None
```

The member object for the user that triggered this interaction, if used in a guild.

#### options `instance-attribute` [#](#crescent.context.InteractionContext.options ""Permanent link"")

```
options: dict[str, Any]
```

The options that were provided by the user.

#### registered\_guild\_id `instance-attribute` [#](#crescent.context.InteractionContext.registered_guild_id ""Permanent link"")

```
registered_guild_id: Snowflake | None
```

The guild ID of the guild that this command is registered to.

#### token `instance-attribute` [#](#crescent.context.InteractionContext.token ""Permanent link"")

```
token: str
```

The token for the interaction.

#### type `instance-attribute` [#](#crescent.context.InteractionContext.type ""Permanent link"")

```
type: int
```

The type of the interaction.

#### user `instance-attribute` [#](#crescent.context.InteractionContext.user ""Permanent link"")

```
user: User
```

The user who triggered this command interaction.

#### version `instance-attribute` [#](#crescent.context.InteractionContext.version ""Permanent link"")

```
version: int
```

Version of the interaction system this interaction is under.

#### into [#](#crescent.context.InteractionContext.into ""Permanent link"")

```
into(context_t: Type[ContextT]) -> ContextT
```

Convert to a context of a different type."
"# Exceptions

### AlreadyRegisteredError [#](#crescent.exceptions.AlreadyRegisteredError ""Permanent link"")

Bases: `[CrescentException](#crescent.exceptions.CrescentException ""<code class=\""doc-symbol doc-symbol-heading doc-symbol-class\""></code>            <span class=\""doc doc-object-name doc-class-name\"">CrescentException</span> (<code>crescent.exceptions.CrescentException</code>)"")`

Command or exception catch function was already registered

### ConverterExceptionMeta `dataclass` [#](#crescent.exceptions.ConverterExceptionMeta ""Permanent link"")

```
ConverterExceptionMeta(
    command: type[ClassCommandProto],
    option_key: str,
    value: Any,
    exception: Exception,
)
```

#### option\_key `instance-attribute` [#](#crescent.exceptions.ConverterExceptionMeta.option_key ""Permanent link"")

```
option_key: str
```

The key of the option on the command class

#### value `instance-attribute` [#](#crescent.exceptions.ConverterExceptionMeta.value ""Permanent link"")

```
value: Any
```

The unconverted value

### ConverterExceptions [#](#crescent.exceptions.ConverterExceptions ""Permanent link"")

```
ConverterExceptions(errors: list[ConverterExceptionMeta])
```

Bases: `[CrescentException](#crescent.exceptions.CrescentException ""<code class=\""doc-symbol doc-symbol-heading doc-symbol-class\""></code>            <span class=\""doc doc-object-name doc-class-name\"">CrescentException</span> (<code>crescent.exceptions.CrescentException</code>)"")`

One or more errors occurred while running the converters for a command.

### CrescentException [#](#crescent.exceptions.CrescentException ""Permanent link"")

Bases: `[Exception](https://docs.python.org/3.9/library/exceptions.html#Exception)`

Base Exception for all exceptions Crescent throws

### InteractionAlreadyAcknowledgedError [#](#crescent.exceptions.InteractionAlreadyAcknowledgedError ""Permanent link"")

Bases: `[CrescentException](#crescent.exceptions.CrescentException ""<code class=\""doc-symbol doc-symbol-heading doc-symbol-class\""></code>            <span class=\""doc doc-object-name doc-class-name\"">CrescentException</span> (<code>crescent.exceptions.CrescentException</code>)"")`

Raise when an interaction is already acknowledged

### PermissionsError [#](#crescent.exceptions.PermissionsError ""Permanent link"")

Bases: `[CrescentException](#crescent.exceptions.CrescentException ""<code class=\""doc-symbol doc-symbol-heading doc-symbol-class\""></code>            <span class=\""doc doc-object-name doc-class-name\"">CrescentException</span> (<code>crescent.exceptions.CrescentException</code>)"")`

Raise when a permission is declared in a subcommand

### PluginAlreadyLoadedError [#](#crescent.exceptions.PluginAlreadyLoadedError ""Permanent link"")

Bases: `[CrescentException](#crescent.exceptions.CrescentException ""<code class=\""doc-symbol doc-symbol-heading doc-symbol-class\""></code>            <span class=\""doc doc-object-name doc-class-name\"">CrescentException</span> (<code>crescent.exceptions.CrescentException</code>)"")`

A plugin is attempted to be loaded but the plugin manager already loaded the plugin."
"# Cooldowns

### cooldown [#](#cooldowns.cooldown ""Permanent link"")

```
cooldown(
    capacity: int,
    period: timedelta,
    *,
    callback: CooldownCallbackT = _default_callback,
    bucket: BucketCallbackT = _default_bucket,
) -> Callable[[Context], Awaitable[HookResult | None]]
```

Ratelimit implementation using a sliding window.

| PARAMETER | DESCRIPTION |
| --- | --- |
| capacity | The amount of times the command can be used within the period.TYPE: int |
| period | The period of time, in seconds, between cooldown resets.TYPE: timedelta |
| callback | Callback for when a user is ratelimited.TYPE: CooldownCallbackT DEFAULT: _default_callback |
| bucket | Callback that returns a key for a bucket.TYPE: BucketCallbackT DEFAULT: _default_bucket |"
"# Tasks

### cronjob [#](#tasks.cron.cronjob ""Permanent link"")

```
cronjob(
    cron: str, /, on_startup: bool = False
) -> Callable[[TaskCallbackT], Includable[Cronjob]]
```

Run a task at the time specified by the cron schedule expression.

| PARAMETER | DESCRIPTION |
| --- | --- |
| cron | The cronjob used to schedule when the callback is run. croniter is used for parsing cron expressions.TYPE: str |
| on_startup | If True, run the callback when this task is started.TYPE: bool DEFAULT: False |

### Loop [#](#tasks.loop.Loop ""Permanent link"")

```
Loop(callback: TaskCallbackT, delay_seconds: float)
```

Bases: `Task`

#### set\_interval [#](#tasks.loop.Loop.set_interval ""Permanent link"")

```
set_interval(
    *,
    hours: int = ...,
    minutes: int = ...,
    seconds: int = ...,
) -> None
```

```
set_interval(timedelta: _timedelta) -> None
```

```
set_interval(
    timedelta: _timedelta | None = None,
    *,
    hours: int = 0,
    minutes: int = 0,
    seconds: int = 0,
) -> None
```

Cancel the currently scheduled task and schedule the next task and future tasks with a new wait time.

###### Example[#](#tasks.loop.Loop.set_interval--example ""Permanent link"")

```
from datetime import datetime
import crescent
from crescent.ext import tasks

bot = hikari.GatewayBot(""..."")
client = crescent.Client(bot)

@client.include
@tasks.loop(seconds=1)
async def my_task():
    print(datetime.now())

@client.include
@crescent.command
async def set_interval(ctx: crescent.Context, interval: int):
    print(f""setting new interval to {interval}"")
    my_task.metadata.set_interval(seconds=interval)
    await ctx.respond(f""Set new interval to {interval}s"")
```

### loop [#](#tasks.loop.loop ""Permanent link"")

```
loop(
    *,
    hours: int = ...,
    minutes: int = ...,
    seconds: int = ...,
) -> retT
```

```
loop(timedelta: _timedelta) -> retT
```

```
loop(
    timedelta: _timedelta | None = None,
    *,
    hours: int = 0,
    minutes: int = 0,
    seconds: int = 0,
) -> retT
```

Run a callback when the bot is started and every time the specified time interval has passed.

### Task [#](#tasks.task.Task ""Permanent link"")

```
Task(callback: TaskCallbackT)
```

Bases: `[ABC](https://docs.python.org/3.9/library/abc.html#abc.ABC ""<code>abc.ABC</code>"")`"
"# Locales

### LocaleMap `dataclass` [#](#locales.LocaleMap ""Permanent link"")

```
LocaleMap(
    _fallback: str,
    da: str | None = None,
    de: str | None = None,
    en_GB: str | None = None,
    en_US: str | None = None,
    es_ES: str | None = None,
    fr: str | None = None,
    hr: str | None = None,
    it: str | None = None,
    lt: str | None = None,
    hu: str | None = None,
    nl: str | None = None,
    no: str | None = None,
    pl: str | None = None,
    pt_BR: str | None = None,
    ro: str | None = None,
    fi: str | None = None,
    sv_SE: str | None = None,
    vi: str | None = None,
    tr: str | None = None,
    cs: str | None = None,
    el: str | None = None,
    bg: str | None = None,
    ru: str | None = None,
    uk: str | None = None,
    hi: str | None = None,
    th: str | None = None,
    zh_CN: str | None = None,
    ja: str | None = None,
    zh_TW: str | None = None,
    ko: str | None = None,
)
```

Bases: `[LocaleBuilder](../../locale/#crescent.locale.LocaleBuilder ""<code class=\""doc-symbol doc-symbol-heading doc-symbol-class\""></code>            <span class=\""doc doc-object-name doc-class-name\"">LocaleBuilder</span> (<code>crescent.LocaleBuilder</code>)"")`

An implementation of `crescent.LocaleBuilder` that allows you to declare locales as kwargs.

```
import crescent
from crescent.ext import locales

@bot.include
@crescent.command(name=locales.LocaleMap(""fallback"", en_US=""english-name"", fr=""french-name""))
async def command(ctx: crescent.Context):
    ...
```

#### fallback `property` [#](#locales.LocaleMap.fallback ""Permanent link"")

```
fallback: str
```

Return the name used when there is no localization for a language.

#### build [#](#locales.LocaleMap.build ""Permanent link"")

```
build() -> dict[str, str]
```

Builds the locales for a command. Returns a `Mapping` of language codes to strings.

[Discord API Docs Localization.](https://discord.com/developers/docs/interactions/application-commands#localization)

### i18n [#](#locales.i18n ""Permanent link"")

```
i18n(fallback: str)
```

Bases: `[LocaleBuilder](../../locale/#crescent.locale.LocaleBuilder ""<code class=\""doc-symbol doc-symbol-heading doc-symbol-class\""></code>            <span class=\""doc doc-object-name doc-class-name\"">LocaleBuilder</span> (<code>crescent.LocaleBuilder</code>)"")`

An implementation of `crescent.LocaleBuilder` that uses `python-i18n`.

> ⚠️ Translations must be loaded before any commands.

```
import crescent
import i18n
from crescent.ext import locales

i18n.add_translation(""name"", ""translated-name"", locale=""en"")

@bot.include
@crescent.command(name=locales.i18n(""name""))
async def command(ctx: crescent.Context):
    ...
```

#### fallback `property` [#](#locales.i18n.fallback ""Permanent link"")

```
fallback: str
```

Return the name used when there is no localization for a language.

#### build [#](#locales.i18n.build ""Permanent link"")

```
build() -> dict[str, str]
```

Builds the locales for a command. Returns a `Mapping` of language codes to strings.

[Discord API Docs Localization.](https://discord.com/developers/docs/interactions/application-commands#localization)"
