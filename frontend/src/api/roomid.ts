import { requestJSON } from './common';

export interface RoomInfo {
    roomid: number;
    uid: number;
    short_id: number;
    uname: string | null;
}

export const getRoomid = async (): Promise<RoomInfo> => {
    return await requestJSON('/roomid');
};

export const setRoomid = async (roomid?: number): Promise<RoomInfo> => {
    if (roomid) {
        return requestJSON('/roomid', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ roomid })
        });
    }
    return getRoomid();
};
