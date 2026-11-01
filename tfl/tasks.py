from huey.contrib.djhuey import task


@task()
def refresh_countdown():
    from . import countdown
    countdown.refresh()
