from core import models, enums


def auto_create_views(image: models.Image):
    # Lets outcreated some views
    if image.rgb_views.count() == 0:
        # Create New Context
        

        # Create New View
        if image.store.c_size == 3:
            rgb_context = models.RGBRenderContext.objects.create(image=image, name="RGB", description="Default RGB Context")

            red_view = models.RGBView.objects.create(image=image, color_map=enums.ColorMapChoices.RED, c_min=0, c_max=1)
            green_view = models.RGBView.objects.create(image=image, color_map=enums.ColorMapChoices.GREEN,  c_min=1, c_max=2)
            blue_view = models.RGBView.objects.create(image=image, color_map=enums.ColorMapChoices.BLUE, c_min=2, c_max=3)

            rgb_context.views.add(red_view, green_view, blue_view)


        else:
            rgb_context = models.RGBRenderContext.objects.create(image=image, name=f"Default", description=f"Default")

            for i in range(image.store.c_size):
                x = models.RGBView.objects.create(image=image,  color_map=enums.ColorMapChoices.VIRIDIS, c_min=i, c_max=i+1, active = i == 0)
                rgb_context.views.add(x)

    else:
        print("Views already created")