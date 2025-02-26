from kante.channel import build_channel


image_broadcast, image_listen = build_channel("image")
file_broadcast, file_listen = build_channel("file")
provenance_broadcast, provenance_listen = build_channel("provenance")
roi_update_broadcast, roi_update_listen = build_channel("roi_update")