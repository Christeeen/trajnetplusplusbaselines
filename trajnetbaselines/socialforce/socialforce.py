import numpy as np
from scipy.interpolate import interp1d

import trajnettools

import socialforce

def predict(input_paths, dest_dict=None, dest_type='interp', sf_params=[0.5, 2.1, 0.3], predict_all=False, args=None):
    pred_length = args.pred_length
    obs_length = args.obs_length

    def init_states(input_paths, start_frame, dest_dict, dest_type):
        initial_state = []
        for i, _ in enumerate(input_paths):
            path = input_paths[i]
            ped_id = path[0].pedestrian
            past_path = [t for t in path if t.frame <= start_frame]
            past_frames = [t.frame for t in path if t.frame <= start_frame]
            future_path = [t for t in path if t.frame > start_frame]
            len_path = len(past_path)

            ## To consider agent or not consider.
            if (start_frame in past_frames):
                curr = past_path[-1]
                
                ## Velocity
                if len_path >= 4:
                    stride = 3
                    prev = past_path[-4]
                else:
                    stride = len_path - 1
                    prev = past_path[-len_path]
                [v_x, v_y] = vel_state(prev, curr, stride)

                ## Destination
                if dest_type == 'true':
                    if dest_dict is not None:
                        [d_x, d_y] = dest_dict[ped_id] 
                    else: 
                        raise ValueError
                elif dest_type == 'interp':
                    [d_x, d_y] = dest_state(past_path, len_path)
                elif dest_type == 'vel':
                    [d_x, d_y] = [pred_length*v_x, pred_length*v_y]
                elif dest_type == 'pred_end':
                    [d_x, d_y] = [future_path[-1].x, future_path[-1].y]
                else:
                    raise NotImplementedError

                ## Initialize State
                initial_state.append([curr.x, curr.y, v_x, v_y, d_x, d_y])
        return np.array(initial_state)

    def vel_state(prev, curr, stride):
        if stride == 0:
            return [0, 0]
        diff = np.array([curr.x - prev.x, curr.y - prev.y])
        theta = np.arctan2(diff[1], diff[0])
        speed = np.linalg.norm(diff) / (stride * 0.4)
        return [speed*np.cos(theta), speed*np.sin(theta)]

    def dest_state(path, length):
        if length == 1:
            return [path[-1].x, path[-1].y]
        x = [t.x for t in path]
        y = [t.y for t in path]
        time = list(range(length))
        f = interp1d(x=time, y=[x, y], fill_value='extrapolate')
        return f(time[-1] + pred_length)

    multimodal_outputs = {}
    primary = input_paths[0]
    neighbours_tracks = []
    frame_diff = primary[1].frame - primary[0].frame
    start_frame = primary[obs_length-1].frame
    first_frame = primary[obs_length-1].frame + frame_diff

    # initialize
    initial_state = init_states(input_paths, start_frame, dest_dict, dest_type)

    fps = 20
    sampling_rate = int(fps / 2.5)

    if len(initial_state):
        # run    
        s = socialforce.Simulator(initial_state, delta_t=1./fps, tau=sf_params[0], 
                                  v0=sf_params[1], sigma=sf_params[2])
        states = np.stack([s.step().state.copy() for _ in range(pred_length*sampling_rate)])
        ## states : pred_length x num_ped x 7
        states = np.array([s for num, s in enumerate(states) if num % sampling_rate == 0])
    else:
        ## Stationary
        past_path = [t for t in input_paths[0] if t.frame == start_frame]
        states = np.stack([[[past_path[0].x, past_path[0].y]] for _ in range(pred_length)])

    # predictions
    for i in range(states.shape[1]):
        ped_id = input_paths[i][0].pedestrian
        if i == 0:
            primary_track = [trajnettools.TrackRow(first_frame + j * frame_diff, ped_id, x, y)
                             for j, (x, y) in enumerate(states[:, i, 0:2])]
        else:
            neighbours_tracks.append([trajnettools.TrackRow(first_frame + j * frame_diff, ped_id, x, y)
                                      for j, (x, y) in enumerate(states[:, i, 0:2])])

    ## Primary Prediction Only
    if not predict_all:
        neighbours_tracks = []

    # Unimodal Prediction
    multimodal_outputs[0] = primary_track, neighbours_tracks
    return multimodal_outputs
