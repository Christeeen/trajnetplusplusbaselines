import shutil
import os
import warnings
from collections import OrderedDict
import argparse

import pickle 
from joblib import Parallel, delayed
import numpy

import trajnettools
import evaluator.write as write
from evaluator.design_pd import Table
from scipy.stats import gaussian_kde

class TrajnetEvaluator:
    def __init__(self, reader_gt, scenes_gt, scenes_id_gt, scenes_sub, indexes, sub_indexes, args):
        self.reader_gt = reader_gt
        
        ##Ground Truth
        self.scenes_gt = scenes_gt
        self.scenes_id_gt = scenes_id_gt

        ##Prediction
        self.scenes_sub = scenes_sub

        ## Dictionary of type of trajectories
        self.indexes = indexes
        self.sub_indexes = sub_indexes

        ## The 4 types of Trajectories
        self.static_scenes = {'N': len(indexes[1])}
        self.linear_scenes = {'N': len(indexes[2])}
        self.forced_non_linear_scenes = {'N': len(indexes[3])}
        self.non_linear_scenes = {'N': len(indexes[4])}

        ## The 4 types of Interactions
        self.lf = {'N': len(sub_indexes[1])}
        self.ca = {'N': len(sub_indexes[2])}
        self.grp = {'N': len(sub_indexes[3])}
        self.others = {'N': len(sub_indexes[4])}

        ## The 4 metrics ADE, FDE, ColI, ColII
        self.average_l2 = {'N': len(scenes_gt)}
        self.final_l2 = {'N': len(scenes_gt)}

        ## Multimodal Prediction
        self.overall_nll = {'N': len(scenes_gt)}
        self.topk_ade = {'N': len(scenes_gt)}
        self.topk_fde = {'N': len(scenes_gt)}
        
        num_predictions = 0
        for track in self.scenes_sub[0][0]:
            if track.prediction_number and track.prediction_number > num_predictions:
                num_predictions = track.prediction_number
        self.num_predictions = num_predictions

        self.pred_length = args.pred_length

    def aggregate(self, name, disable_collision):

        ## Overall Single Mode Scores
        average = 0.0
        final = 0.0

        ## Overall Multi Mode Scores
        average_topk_ade = 0
        average_topk_fde = 0
        average_nll = 0

        ## Aggregates ADE, FDE and Collision in GT & Pred, Topk ADE-FDE , NLL for each category & sub_category
        score = {1: [0.0, 0.0, 0, 0, 0, 0.0, 0.0, 0.0], 2: [0.0, 0.0, 0, 0, 0, 0.0, 0.0, 0.0], \
                 3: [0.0, 0.0, 0, 0, 0, 0.0, 0.0, 0.0], 4: [0.0, 0.0, 0, 0, 0, 0.0, 0.0, 0.0]}
        sub_score =  {1: [0.0, 0.0, 0, 0, 0, 0.0, 0.0, 0.0], 2: [0.0, 0.0, 0, 0, 0, 0.0, 0.0, 0.0], \
                      3: [0.0, 0.0, 0, 0, 0, 0.0, 0.0, 0.0], 4: [0.0, 0.0, 0, 0, 0, 0.0, 0.0, 0.0]}

        ## Iterate
        for i in range(len(self.scenes_gt)):
            ground_truth = self.scenes_gt[i]
            
            ## Get Keys and Sub_keys
            keys = []
            sub_keys = []

            ## Main
            for key in list(score.keys()):
                if self.scenes_id_gt[i] in self.indexes[key]:
                    keys.append(key)
            # ## Sub
            for sub_key in list(sub_score.keys()):
                if self.scenes_id_gt[i] in self.sub_indexes[sub_key]:
                    sub_keys.append(sub_key)

            ## Extract Prediction Frames
            primary_tracks_all = [t for t in self.scenes_sub[i][0] if t.scene_id == self.scenes_id_gt[i]]
            neighbours_tracks_all = [[t for t in self.scenes_sub[i][j] if t.scene_id == self.scenes_id_gt[i]] for j in range(1, len(self.scenes_sub[i]))]

##### --------------------------------------------------- SINGLE -------------------------------------------- ####


            primary_tracks = [t for t in primary_tracks_all if t.prediction_number == 0]
            neighbours_tracks = [[t for t in neighbours_tracks_all[j] if t.prediction_number == 0] for j in range(len(neighbours_tracks_all))]

            frame_gt = [t.frame for t in ground_truth[0]][-self.pred_length:]
            frame_pred = [t.frame for t in primary_tracks]

            ## To verify if same scene
            if frame_gt != frame_pred:
                raise Exception('frame numbers are not consistent')

            average_l2 = trajnettools.metrics.average_l2(ground_truth[0], primary_tracks)
            final_l2 = trajnettools.metrics.final_l2(ground_truth[0], primary_tracks)

            if not disable_collision:
               
                ## Collisions in GT
                # person_radius=0.1
                for j in range(1, len(ground_truth)):
                    if trajnettools.metrics.collision(primary_tracks, ground_truth[j]):
                        for key in keys:
                            score[key][2] += 1
                        ## Sub
                        for sub_key in sub_keys:
                            sub_score[sub_key][2] += 1
                        break


                ## Collision in Predictions 
                flat_neigh_list = [item for sublist in neighbours_tracks for item in sublist]
                if len(flat_neigh_list): 
                    for key in keys:
                        score[key][4] += 1
                        for j in range(len(neighbours_tracks)):
                            if trajnettools.metrics.collision(primary_tracks, neighbours_tracks[j]):
                                score[key][3] += 1
                                break
                    ## Sub
                    for sub_key in sub_keys:
                        sub_score[sub_key][4] += 1
                        for j in range(len(neighbours_tracks)):
                            if trajnettools.metrics.collision(primary_tracks, neighbours_tracks[j]):
                                sub_score[sub_key][3] += 1
                                break  


            # aggregate FDE and ADE
            average += average_l2
            final += final_l2
            for key in keys:
                score[key][0] += average_l2
                score[key][1] += final_l2     

            ## Sub
            for sub_key in sub_keys:
                sub_score[sub_key][0] += average_l2
                sub_score[sub_key][1] += final_l2  

##### --------------------------------------------------- SINGLE -------------------------------------------- ####

##### --------------------------------------------------- Top 3 -------------------------------------------- ####

            if self.num_predictions > 1:
                topk_ade, topk_fde = self.topk(primary_tracks_all, ground_truth[0])

                average_topk_ade += topk_ade
                ##Key
                for key in keys:
                    score[key][5] += topk_ade
                ## SubKey
                for sub_key in sub_keys:
                    sub_score[sub_key][5] += topk_ade

                average_topk_fde += topk_fde
                ##Key
                for key in keys:
                    score[key][6] += topk_fde
                ## SubKey
                for sub_key in sub_keys:
                    sub_score[sub_key][6] += topk_fde

##### --------------------------------------------------- Top 3 -------------------------------------------- ####

##### --------------------------------------------------- NLL -------------------------------------------- ####
            if self.num_predictions > 98:
                nll = self.nll(primary_tracks_all, ground_truth[0], pred_length=self.pred_length)

                average_nll += nll
                ##Key
                for key in keys:
                    score[key][7] += nll
                ## SubKey
                for sub_key in sub_keys:
                    sub_score[sub_key][7] += nll
##### --------------------------------------------------- NLL -------------------------------------------- ####

        ## Average ADE and FDE
        average /= len(self.scenes_gt)
        final /= len(self.scenes_gt)

        ## Average TopK ADE and Topk FDE and NLL
        average_topk_ade /= len(self.scenes_gt)
        average_topk_fde /= len(self.scenes_gt)
        average_nll /= len(self.scenes_gt)

        ## Average categories
        for key in list(score.keys()):
            if self.indexes[key]:
                score[key][0] /= len(self.indexes[key])
                score[key][1] /= len(self.indexes[key])

                score[key][5] /= len(self.indexes[key])
                score[key][6] /= len(self.indexes[key])
                score[key][7] /= len(self.indexes[key])

        ## Average subcategories
        ## Sub
        for sub_key in list(sub_score.keys()):
            if self.sub_indexes[sub_key]:
                sub_score[sub_key][0] /= len(self.sub_indexes[sub_key])
                sub_score[sub_key][1] /= len(self.sub_indexes[sub_key]) 

                sub_score[sub_key][5] /= len(self.sub_indexes[sub_key])
                sub_score[sub_key][6] /= len(self.sub_indexes[sub_key])
                sub_score[sub_key][7] /= len(self.sub_indexes[sub_key])

        # ##Adding value to dict
        self.average_l2[name] = average
        self.final_l2[name] = final

        ##APPEND to overall keys
        self.overall_nll[name] = average_nll
        self.topk_ade[name] = average_topk_ade
        self.topk_fde[name] = average_topk_fde

        ## Main
        self.static_scenes[name] = score[1]
        self.linear_scenes[name] = score[2]
        self.forced_non_linear_scenes[name] = score[3]
        self.non_linear_scenes[name] = score[4]

        ## Sub_keys
        self.lf[name] = sub_score[1]
        self.ca[name] = sub_score[2]
        self.grp[name] = sub_score[3]
        self.others[name] = sub_score[4]

        return self

    def topk(self, primary_tracks, ground_truth, topk=3):
        ## TopK multimodal 

        l2 = 1e10
        ## preds: Pred_len x Num_preds x 2
        for pred_num in range(topk):
            primary_prediction = [t for t in primary_tracks if t.prediction_number == pred_num]
            tmp_score = trajnettools.metrics.final_l2(ground_truth, primary_prediction)
            if tmp_score < l2:      
                l2 = tmp_score 
                topk_fde = tmp_score
                topk_ade = trajnettools.metrics.average_l2(ground_truth, primary_prediction)

        return topk_ade, topk_fde

    def nll(self, primary_tracks, ground_truth, pred_length=12, log_pdf_lower_bound=-20):
        ## Inspired from Boris.
        gt = numpy.array([[t.x, t.y] for t in ground_truth][-pred_length:])
        frame_gt = [t.frame for t in ground_truth][-pred_length:]
        preds = numpy.array([[[t.x, t.y] for t in primary_tracks if t.frame == frame] for frame in frame_gt])
        ## preds: Pred_len x Num_preds x 2

        ## To verify if 100 predictions
        if preds.shape[1] != 100:
            raise Exception('Need 100 predictions')

        pred_len = len(frame_gt)

        ll = 0.0
        same_pred = 0
        for timestep in range(pred_len):
            curr_gt = gt[timestep]
            try:
                scipy_kde = gaussian_kde(preds[timestep].T)
                # We need [0] because it's a (1,)-shaped numpy array.
                log_pdf = numpy.clip(scipy_kde.logpdf(curr_gt.T), a_min=log_pdf_lower_bound, a_max=None)[0]
                ll += log_pdf
            except:
                same_pred += 1

        if same_pred == pred_len:
            raise Exception('All 100 Predictions are Identical')

        ll = ll / (pred_len - same_pred)
        return ll


    def result(self):
        return self.average_l2, self.final_l2, \
               self.static_scenes, self.linear_scenes, self.forced_non_linear_scenes, self.non_linear_scenes, \
               self.lf, self.ca, self.grp, self.others, \
               self.topk_ade, self.topk_fde, self.overall_nll



def eval(gt, input_file, args, input_file2=None):
    # Ground Truth
    reader_gt = trajnettools.Reader(gt, scene_type='paths')
    scenes_gt = [s for _, s in reader_gt.scenes()]
    scenes_id_gt = [s_id for s_id, _ in reader_gt.scenes()]

    # Scene Predictions
    reader_sub = trajnettools.Reader(input_file, scene_type='paths')
    scenes_sub = [s for _, s in reader_sub.scenes()]

    ## indexes is dictionary deciding which scenes are in which type
    indexes = {}
    for i in range(1,5):
        indexes[i] = []
    ## sub-indexes
    sub_indexes = {}
    for i in range(1,5):
        sub_indexes[i] = []
    for scene in reader_gt.scenes_by_id:
        tags = reader_gt.scenes_by_id[scene].tag
        main_tag = tags[0:1]
        sub_tags = tags[1]
        for ii in range(1, 5):
            if ii in main_tag:
                indexes[ii].append(scene)
            if ii in sub_tags:
                sub_indexes[ii].append(scene)

    # Evaluate
    evaluator = TrajnetEvaluator(reader_gt, scenes_gt, scenes_id_gt, scenes_sub, indexes, sub_indexes, args)
    evaluator.aggregate('kf', args.disable_collision)

    return evaluator.result()

def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default='trajdata',
                        help='directory of data to test')    
    parser.add_argument('--output', required=True, nargs='+',
                        help='relative path to saved model')
    parser.add_argument('--obs_length', default=9, type=int,
                        help='observation length')
    parser.add_argument('--pred_length', default=12, type=int,
                        help='prediction length')
    parser.add_argument('--disable-write', action='store_true',
                        help='disable writing new files')
    parser.add_argument('--disable-collision', action='store_true',
                        help='disable collision metrics')
    parser.add_argument('--labels', required=False, nargs='+',
                        help='labels of models')
    args = parser.parse_args()

    ## Path to the data folder name to predict 
    args.data = 'DATA_BLOCK/' + args.data + '/'

    ## Test_pred : Folders for saving model predictions
    args.data = args.data + 'test_pred/'


    ## Writes to Test_pred
    ### Does this overwrite existing predictions? No. ###
    if not args.disable_write:
        write.main(args)

    ## Evaluates test_pred with test_private
    names = []
    for model in args.output:
        names.append(model.split('/')[-1].replace('.pkl', ''))

    ## labels
    if args.labels:
        labels = args.labels
    else:
        labels = names

    # Initiate Result Table
    table = Table()

    for num, name in enumerate(names):
        print(name)

        result_file = args.data.replace('pred', 'results') + name

        ## If result was pre-calculated and saved, Load
        if os.path.exists(result_file + '/results.pkl'):
            print("Loading Saved Results")
            with open(result_file + '/results.pkl', 'rb') as handle:
                [final_result, sub_final_result] = pickle.load(handle)
            table.add_result(labels[num], final_result, sub_final_result)

        # ## Else, Calculate results and save
        else:
            list_sub = sorted([f for f in os.listdir(args.data + name)
                               if not f.startswith('.')])

            submit_datasets = [args.data + name + '/' + f for f in list_sub]
            true_datasets = [args.data.replace('pred', 'private') + f for f in list_sub]

            ## Evaluate submitted datasets with True Datasets [The main eval function]
            # results = {submit_datasets[i].replace(args.data, '').replace('.ndjson', ''):
            #             eval(true_datasets[i], submit_datasets[i], args)
            #            for i in range(len(true_datasets))}

            results_list = Parallel(n_jobs=4)(delayed(eval)(true_datasets[i], submit_datasets[i], args)
                                                            for i in range(len(true_datasets)))
            results = {submit_datasets[i].replace(args.data, '').replace('.ndjson', ''):
                       results_list[i] for i in range(len(true_datasets))}

            # print(results)
            ## Generate results 
            final_result, sub_final_result = table.add_entry(labels[num], results)

            ## Save results as pkl (to avoid computation again) 
            os.makedirs(result_file)
            with open(result_file + '/results.pkl', 'wb') as handle:
                pickle.dump([final_result, sub_final_result], handle, protocol=pickle.HIGHEST_PROTOCOL)

    ## Make Result Table 
    table.print_table()
 
if __name__ == '__main__':
    main()

